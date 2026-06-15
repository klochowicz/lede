# Cross-Source Briefing — Web Surface Implementation Plan (Plan 2 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a Django web surface on top of the pipeline from Plan 1 — a dashboard + digest archive, Postgres full-text search over items, an installable PWA, and GitHub OAuth login.

**Architecture:** Read-side Django views over the same Postgres models the Celery pipeline writes (the CQRS-ish split the spec calls out: Celery writes, Django reads). FTS uses a populated `search_vector` (`GIN`-indexed) queried with `SearchQuery`/`SearchRank`. `django-allauth` gates the surface behind GitHub login. A minimal service worker makes it installable (not offline-first).

**Tech Stack:** Django 6 views/templates, `django.contrib.postgres.search`, `django-allauth` (GitHub), static `manifest.json` + `sw.js`. Same tooling as Plan 1 (uv, mise, ruff `ANN`, pyright `standard`, pytest-django).

**Prerequisite:** Plan 1 is implemented (models, tasks, LLM layer, admin). This plan assumes `Item.search_vector` exists as a `SearchVectorField(null=True)` and that `summarise_item` is the place a summary first lands.

**Type-annotation policy:** identical to Plan 1 — all signatures annotated (views return `HttpResponse`), domain types over loose containers, `ANN` (ruff) + `mypy` (with the django-stubs plugin) enforce it in `mise run ci`, tests/migrations exempt.

---

## File Structure

| Path | Responsibility |
|---|---|
| `briefing/tasks.py` (modify) | populate `search_vector` when a summary lands; add `kick_off_weekly` |
| `briefing/search.py` | `search_items(query: str) -> QuerySet[Item]` — FTS query, reused by view + tests |
| `briefing/views.py` | `dashboard`, `archive`, `digest_detail`, `search` |
| `briefing/urls.py` | app urlconf |
| `config/urls.py` (modify) | include `briefing.urls` + `allauth.urls` |
| `briefing/templates/briefing/base.html` | layout, nav, PWA registration |
| `briefing/templates/briefing/dashboard.html` | latest digest |
| `briefing/templates/briefing/archive.html` | digest list |
| `briefing/templates/briefing/digest_detail.html` | one digest's themes |
| `briefing/templates/briefing/search.html` | FTS results |
| `briefing/static/manifest.json` | PWA manifest |
| `briefing/static/sw.js` | minimal service worker (install criteria) |
| `config/settings/base.py` (modify) | allauth apps/middleware/site; weekly beat entry |

---

## Task 1: Populate `search_vector` when a summary lands

FTS needs the vector kept current. The cheapest correct hook is right after `summarise_item` writes a summary (and after `poll_source` re-summarise clears it). We update via SQL expression so Postgres computes `to_tsvector`.

**Files:**
- Modify: `briefing/tasks.py`
- Test: `tests/test_search_vector.py`

- [ ] **Step 1: Write the failing test**

`tests/test_search_vector.py`:

```python
from unittest.mock import MagicMock, patch

from django.contrib.postgres.search import SearchQuery

from briefing.models import Item, Source
from briefing.tasks import summarise_item


def test_summarise_populates_search_vector(db):
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    item = Item.objects.create(
        source=source, external_id="e1", url="https://x/1", content_hash="h1",
        title="Quantum computing breakthrough", raw_content="body",
    )
    backend = MagicMock()
    backend.condense.return_value = "A summary about superconductors."
    with patch("briefing.tasks.get_backend", return_value=backend):
        summarise_item(item.id)

    hits = Item.objects.filter(search_vector=SearchQuery("superconductors"))
    assert item in hits
    quantum_hits = Item.objects.filter(search_vector=SearchQuery("quantum"))
    assert item in quantum_hits
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_search_vector.py -v`
Expected: FAIL — `search_vector` is null, neither query matches.

- [ ] **Step 3: Update `summarise_item` to refresh the vector**

In `briefing/tasks.py`, add the import and one line after the summary is saved:

```python
from django.contrib.postgres.search import SearchVector
```

In `summarise_item`, immediately after `item.save(update_fields=[...])` (the success path):

```python
    Item.objects.filter(id=item_id).update(
        search_vector=SearchVector("title", "summary", config="english")
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_search_vector.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add briefing/tasks.py tests/test_search_vector.py
git commit -m "populate Item.search_vector when a summary is written"
```

---

## Task 2: `search_items` FTS query helper

**Files:**
- Create: `briefing/search.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: Write the failing test**

`tests/test_search.py`:

```python
from django.contrib.postgres.search import SearchVector
from django.utils import timezone

from briefing.models import Item, Source
from briefing.search import search_items


def _item(source, ext, title, summary):
    item = Item.objects.create(
        source=source, external_id=ext, url=f"https://x/{ext}", content_hash=ext,
        title=title, summary=summary, summarised_at=timezone.now(),
    )
    Item.objects.filter(id=item.id).update(
        search_vector=SearchVector("title", "summary", config="english")
    )
    return item


def test_search_ranks_and_filters(db):
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    relevant = _item(source, "e1", "Rust async runtime", "tokio and futures explained")
    _item(source, "e2", "Baking sourdough", "hydration and crumb")

    results = list(search_items("tokio"))
    assert relevant in results
    assert len(results) == 1


def test_search_blank_query_returns_empty(db):
    assert list(search_items("   ")) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_search.py -v`
Expected: FAIL — `briefing.search` not found.

- [ ] **Step 3: Write `briefing/search.py`**

```python
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import QuerySet

from briefing.models import Item


def search_items(query: str) -> QuerySet[Item]:
    cleaned = query.strip()
    if not cleaned:
        return Item.objects.none()
    search_query = SearchQuery(cleaned, config="english")
    return (
        Item.objects.filter(search_vector=search_query)
        .annotate(rank=SearchRank("search_vector", search_query))
        .order_by("-rank")
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_search.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add briefing/search.py tests/test_search.py
git commit -m "add ranked Postgres FTS search_items helper"
```

---

## Task 3: Views + urlconf + base template

**Files:**
- Create: `briefing/views.py`, `briefing/urls.py`, `briefing/templates/briefing/base.html`,
  `dashboard.html`, `archive.html`, `digest_detail.html`, `search.html`
- Modify: `config/urls.py`
- Test: `tests/test_views.py`

- [ ] **Step 1: Write the failing test**

`tests/test_views.py`:

```python
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from briefing.models import Digest, Theme


def _login(client):
    User.objects.create_user("u", password="pw")
    client.login(username="u", password="pw")


def test_dashboard_shows_latest_digest(client, db):
    _login(client)
    digest = Digest.objects.create(
        kind="daily", period_start=timezone.now(), period_end=timezone.now(),
        status=Digest.Status.SENT,
    )
    Theme.objects.create(digest=digest, title="Headline Theme", narrative="n", importance=9)
    resp = client.get(reverse("briefing:dashboard"))
    assert resp.status_code == 200
    assert b"Headline Theme" in resp.content


def test_views_require_login(client, db):
    resp = client.get(reverse("briefing:dashboard"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.headers["Location"]


def test_search_view_renders_hits(client, db):
    from django.contrib.postgres.search import SearchVector

    from briefing.models import Item, Source
    _login(client)
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    item = Item.objects.create(
        source=source, external_id="e1", url="https://x/1", content_hash="h1",
        title="Kubernetes operators", summary="reconcile loops", summarised_at=timezone.now(),
    )
    Item.objects.filter(id=item.id).update(
        search_vector=SearchVector("title", "summary", config="english")
    )
    resp = client.get(reverse("briefing:search"), {"q": "kubernetes"})
    assert resp.status_code == 200
    assert b"Kubernetes operators" in resp.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_views.py -v`
Expected: FAIL — no `briefing:dashboard` route.

- [ ] **Step 3: Write the views**

`briefing/views.py`:

```python
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from briefing.models import Digest
from briefing.search import search_items


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    latest = Digest.objects.filter(status=Digest.Status.SENT).order_by("-period_end").first()
    return render(request, "briefing/dashboard.html", {"digest": latest})


@login_required
def archive(request: HttpRequest) -> HttpResponse:
    digests = Digest.objects.order_by("-period_end")
    return render(request, "briefing/archive.html", {"digests": digests})


@login_required
def digest_detail(request: HttpRequest, pk: int) -> HttpResponse:
    digest = get_object_or_404(Digest, pk=pk)
    return render(request, "briefing/digest_detail.html", {"digest": digest})


@login_required
def search(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "")
    return render(request, "briefing/search.html", {"query": query, "results": search_items(query)})
```

- [ ] **Step 4: Write `briefing/urls.py` and wire `config/urls.py`**

`briefing/urls.py`:

```python
from django.urls import path

from briefing import views

app_name = "briefing"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("archive/", views.archive, name="archive"),
    path("digest/<int:pk>/", views.digest_detail, name="digest_detail"),
    path("search/", views.search, name="search"),
]
```

Replace `config/urls.py` with:

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("", include("briefing.urls")),
]
```

Add to `config/settings/base.py` so `@login_required` redirects to the allauth login:

```python
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
```

- [ ] **Step 5: Write the templates**

`briefing/templates/briefing/base.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Briefing{% endblock %}</title>
  <link rel="manifest" href="{% load static %}{% static 'manifest.json' %}">
</head>
<body>
  <nav>
    <a href="{% url 'briefing:dashboard' %}">Latest</a>
    <a href="{% url 'briefing:archive' %}">Archive</a>
    <form action="{% url 'briefing:search' %}" method="get">
      <input name="q" placeholder="Search items" value="{{ query|default:'' }}">
    </form>
  </nav>
  <main>{% block content %}{% endblock %}</main>
  <script>
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("{% static 'sw.js' %}");
    }
  </script>
</body>
</html>
```

`briefing/templates/briefing/dashboard.html`:

```html
{% extends "briefing/base.html" %}
{% block content %}
  {% if digest %}
    <h1>{{ digest.get_kind_display }} briefing</h1>
    {% for theme in digest.themes.all %}
      <section><h2>{{ theme.title }}</h2><p>{{ theme.narrative }}</p>
        <ul>{% for link in theme.theme_items.all %}
          <li><a href="{{ link.item.url }}">{{ link.item.title }}</a> — {{ link.rationale }}</li>
        {% endfor %}</ul>
      </section>
    {% endfor %}
  {% else %}
    <p>No digest yet.</p>
  {% endif %}
{% endblock %}
```

`briefing/templates/briefing/archive.html`:

```html
{% extends "briefing/base.html" %}
{% block content %}
  <h1>Archive</h1>
  <ul>{% for digest in digests %}
    <li><a href="{% url 'briefing:digest_detail' digest.pk %}">
      {{ digest.get_kind_display }} — {{ digest.period_end|date:"j M Y" }}</a></li>
  {% empty %}<li>Nothing archived yet.</li>{% endfor %}</ul>
{% endblock %}
```

`briefing/templates/briefing/digest_detail.html`:

```html
{% extends "briefing/base.html" %}
{% block content %}
  <h1>{{ digest.get_kind_display }} — {{ digest.period_end|date:"j M Y" }}</h1>
  {% for theme in digest.themes.all %}
    <section><h2>{{ theme.title }}</h2><p>{{ theme.narrative }}</p></section>
  {% endfor %}
{% endblock %}
```

`briefing/templates/briefing/search.html`:

```html
{% extends "briefing/base.html" %}
{% block content %}
  <h1>Search</h1>
  {% if query %}<p>Results for "{{ query }}":</p>{% endif %}
  <ul>{% for item in results %}
    <li><a href="{{ item.url }}">{{ item.title }}</a> — {{ item.summary }}</li>
  {% empty %}<li>No matches.</li>{% endfor %}</ul>
{% endblock %}
```

- [ ] **Step 6: Run the view tests**

Run: `uv run pytest tests/test_views.py -v`
Expected: the `dashboard`/`search` tests PASS; `test_views_require_login` PASSES once allauth urls exist — if allauth isn't installed yet, run this test after Task 5 and proceed; the other two pass now.

Note: `test_views_require_login` depends on the `/accounts/login/` route from Task 5. If running strictly TDD, write Task 5 (allauth) before this step's full green, or temporarily assert a 302 to any login URL. Recommended order: do Task 5 next, then re-run this suite.

- [ ] **Step 7: Commit**

```bash
git add briefing/views.py briefing/urls.py briefing/templates/ config/urls.py config/settings/base.py tests/test_views.py
git commit -m "add dashboard/archive/detail/search views, urlconf, and templates"
```

---

## Task 4: PWA — manifest + minimal service worker

**Files:**
- Create: `briefing/static/manifest.json`, `briefing/static/sw.js`
- Test: `tests/test_pwa.py`

- [ ] **Step 1: Write the failing test**

`tests/test_pwa.py`:

```python
import json
from pathlib import Path

STATIC = Path(__file__).parent.parent / "briefing" / "static"


def test_manifest_is_valid_and_installable():
    manifest = json.loads((STATIC / "manifest.json").read_text())
    assert manifest["name"]
    assert manifest["start_url"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["icons"], "installable PWA needs at least one icon"


def test_service_worker_registers_lifecycle_events():
    sw = (STATIC / "sw.js").read_text()
    assert "install" in sw
    assert "fetch" in sw
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pwa.py -v`
Expected: FAIL — files don't exist.

- [ ] **Step 3: Create the manifest and service worker**

`briefing/static/manifest.json`:

```json
{
  "name": "Cross-Source Briefing",
  "short_name": "Briefing",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#111111",
  "icons": [
    {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
```

`briefing/static/sw.js` (minimal — satisfies installability, not offline-first):

```javascript
// Minimal service worker: present so the app is installable. Deliberately no caching (v1).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {
  // Pass-through: let the network handle every request. Offline-first is out of scope for v1.
});
```

- [ ] **Step 4: Provide placeholder icons**

The manifest references `icon-192.png` / `icon-512.png`. Generate two solid-colour PNGs so install criteria pass:

```bash
uv run python -c "
from pathlib import Path
import struct, zlib
def png(path, size):
    def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    raw = b''.join(b'\x00' + b'\x11\x11\x11' * size for _ in range(size))
    ihdr = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
png('briefing/static/icon-192.png', 192)
png('briefing/static/icon-512.png', 512)
"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_pwa.py -v`
Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add briefing/static/
git commit -m "add PWA manifest, minimal service worker, and placeholder icons"
```

---

## Task 5: GitHub OAuth login via django-allauth

**Files:**
- Modify: `pyproject.toml` (add `django-allauth`), `config/settings/base.py`, `config/settings/local.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Add the dependency**

In `pyproject.toml` `[project].dependencies`, add `"django-allauth>=65.0"`, then:

Run: `uv sync`

- [ ] **Step 2: Write the failing test**

`tests/test_auth.py`:

```python
from django.urls import reverse


def test_login_page_offers_github(client, db):
    resp = client.get(reverse("account_login"))
    assert resp.status_code == 200


def test_socialaccount_github_provider_configured(settings):
    assert "allauth.socialaccount.providers.github" in settings.INSTALLED_APPS
    assert "github" in settings.SOCIALACCOUNT_PROVIDERS
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL — `account_login` route / provider config missing.

- [ ] **Step 4: Configure allauth in `config/settings/base.py`**

Add `django.contrib.sites` and the allauth apps to `INSTALLED_APPS`:

```python
INSTALLED_APPS += [
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.github",
]
```

Add the middleware (after `AuthenticationMiddleware`):

```python
MIDDLEWARE += ["allauth.account.middleware.AccountMiddleware"]
```

Add settings:

```python
SITE_ID = 1
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
SOCIALACCOUNT_PROVIDERS = {
    "github": {
        "APPS": [
            {
                "client_id": env("GITHUB_CLIENT_ID", default=""),
                "secret": env("GITHUB_CLIENT_SECRET", default=""),
                "key": "",
            }
        ],
        "SCOPE": ["read:user"],
    }
}
# Leave SOCIALACCOUNT_LOGIN_ON_GET at its default (False): provider login must be a
# CSRF-protected POST, not a GET (avoids login CSRF). Do not set it to True.
```

- [ ] **Step 5: Migrate and run the test**

Run: `uv run python manage.py migrate && uv run pytest tests/test_auth.py -v`
Expected: both PASS. (The `django.contrib.sites` + allauth tables get created.)

- [ ] **Step 6: Re-run the view tests now that `/accounts/login/` exists**

Run: `uv run pytest tests/test_views.py -v`
Expected: all three PASS, including `test_views_require_login`.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock config/settings/base.py tests/test_auth.py
git commit -m "add django-allauth GitHub OAuth login gating the web surface"
```

---

## Task 6: Weekly digest beat entry

Plan 1 wired the daily digest. Mirror it for weekly (the spec's daily|weekly requirement).

**Files:**
- Modify: `briefing/tasks.py`, `config/settings/base.py`
- Test: `tests/test_kick_off_weekly.py`

- [ ] **Step 1: Write the failing test**

`tests/test_kick_off_weekly.py`:

```python
from unittest.mock import patch

from briefing.tasks import kick_off_weekly


def test_kick_off_weekly_spans_seven_days(db):
    with patch("briefing.tasks.kick_off_digest") as kick:
        kick_off_weekly()
    kind, start_iso, end_iso = kick.call_args.args
    assert kind == "weekly"
    from datetime import datetime
    span = datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)
    assert span.days == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_kick_off_weekly.py -v`
Expected: FAIL — `cannot import name 'kick_off_weekly'`.

- [ ] **Step 3: Add `kick_off_weekly` and the beat entry**

Append to `briefing/tasks.py`:

```python
@shared_task
def kick_off_weekly() -> None:
    end = timezone.now()
    kick_off_digest("weekly", (end - timedelta(days=7)).isoformat(), end.isoformat())
```

Add to `CELERY_BEAT_SCHEDULE` in `config/settings/base.py`:

```python
    "weekly-digest": {
        "task": "briefing.tasks.kick_off_weekly",
        "schedule": crontab(hour=8, minute=0, day_of_week="mon"),
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_kick_off_weekly.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add briefing/tasks.py config/settings/base.py tests/test_kick_off_weekly.py
git commit -m "add weekly digest kick-off task and Monday beat schedule"
```

---

## Task 7: Full suite green + manual web smoke

**Files:** none (verification)

- [ ] **Step 1: Run the whole suite + lint**

Run: `mise run ci`
Expected: ruff (incl. `ANN`) clean, pyright `standard` clean, all tests PASS across both plans.

- [ ] **Step 2: Manual web smoke**

```bash
docker compose up -d postgres redis
uv run python manage.py migrate
uv run python manage.py runserver
```

- Visit `http://localhost:8000/` → redirected to `/accounts/login/`.
- Configure a GitHub OAuth app (callback `http://localhost:8000/accounts/github/login/callback/`), set `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET`, log in.
- With a digest already built (Plan 1 smoke), confirm the dashboard renders themes, the archive lists digests, a digest detail opens, and a full-text search returns ranked item hits.
- On a phone (same LAN), open the site → browser offers **"Install"** (manifest + SW present).

- [ ] **Step 3: Commit any smoke fixups**

```bash
git add -A && git commit -m "web-surface smoke-test fixups"   # only if needed
```

---

## Self-Review (against the spec)

- **Spec coverage:** PWA manifest + minimal service worker, installable-not-offline-first (Task 4) ✓; dashboard + digest archive views (Task 3) ✓; Postgres full-text search — population (Task 1), ranked query helper (Task 2), search UI (Task 3) ✓; `django-allauth` GitHub OAuth login (Task 5) ✓; daily **and weekly** digest (weekly completed here, Task 6) ✓.
- **CQRS-ish split honoured:** every view in Task 3 is read-only over models the Celery pipeline writes; no view enqueues or mutates. The only write this plan adds to the pipeline is the FTS-vector refresh (Task 1), which lives in the Celery task, not a view.
- **Placeholder scan:** none — all templates, views, settings deltas, and the icon-generation command are concrete. The deliberate ordering dependency (view login-redirect test needs allauth) is called out in Task 3 Step 6 with the resolution.
- **Type consistency:** `search_items(query: str) -> QuerySet[Item]` signature matches its view call site; all four views return `HttpResponse`; `Digest.Status.SENT` / `get_kind_display` usage matches the Plan 1 model.

---

## Execution Handoff

**Plan 2 complete and saved to `docs/superpowers/plans/2026-06-15-cross-source-briefing-web-surface.md`.**

Recommended overall sequence: execute **Plan 1 (pipeline) first**, subagent-driven, then **Plan 2 (this one)** against the working pipeline. The FTS and views are far easier to smoke-test once real items and digests exist.
