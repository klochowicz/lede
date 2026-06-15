# Cross-Source Briefing — Pipeline Implementation Plan (Plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Celery-driven content pipeline — poll content sources on a schedule, condense each item with an LLM, synthesise a window of items into cross-source themes, persist them, and render/send an email digest.

**Architecture:** Django 6 owns the Postgres data model and a thin admin surface for managing sources. Celery 5 owns the scheduled + fan-out + chorded + retried pipeline. A provider-agnostic `LLMBackend` protocol (`briefing/llm.py`) hides three interchangeable LLM backends. The committed default backend is `claude-api` (reproducible); local-dev settings override to `claude-subscription`.

**Tech Stack:** Python 3.12, uv (deps), mise (tasks), Django 6, Celery 5, Redis (broker+result), Postgres 16, `feedparser`, `anthropic`, `openai` (DeepSeek), `claude-agent-sdk`/`claude` CLI, ruff, pyright, pytest-django.

**Scope note:** This is Plan 1 of 2. The web/PWA/FTS-search/allauth surface is Plan 2. Plan 1 ends with a fully testable pipeline: add a `Source` in admin → poll → summarise → build digest → render email (console backend).

---

## Type-annotation policy

Annotate where it buys safety or documents intent; don't annotate where it's noise. Enforced by `ruff` (`ANN` rules) + `mypy` (with the `django-stubs` mypy plugin) in `mise run ci`, so a missing or wrong annotation fails CI. (Note: implementation switched from pyright to mypy mid-build — pyright + django-stubs can't run the stubs' mypy plugin, so it false-positived on `get_FOO_display`, Celery `.delay`, and `env()` defaults.)

- **Always annotate function signatures** — every parameter and the return type, in `briefing/` and `config/`. Celery tasks included (`-> list[int]`, `-> int | None`, `-> None`). This is the line `ruff ANN` enforces.
- **Use precise domain types, not bare containers.** The LLM protocol returns `list[dict]` at the boundary, but model-facing helpers should say what they mean: `RawItem` (a frozen dataclass) instead of a loose dict; `Source.Kind`/`Digest.Status` enums instead of `str` literals at call sites.
- **`X | None` directly** — native on 3.12, no `from __future__ import annotations` needed. Only add that import to a module that needs forward references (a type referenced before it's defined); the pipeline modules here don't.
- **Lean on the stubs.** `django-stubs` (+ its mypy plugin) gives `Item.objects` / `QuerySet[Item]` real types — let mypy infer locals from them rather than hand-annotating every `queryset` variable.
- **Where annotations DON'T pay off** (and `ANN` is intentionally relaxed): `test_*` functions (return type is always `None`, signature is self-evident) and generated migrations. Don't annotate local variables whose type pyright already infers — that's the noise to avoid.
- **No `Any` as an escape hatch.** If a third-party return is loosely typed, narrow it at the boundary (e.g. parse the LLM JSON into the known theme shape) rather than letting `Any` leak inward.

---

## File Structure

| Path | Responsibility |
|---|---|
| `pyproject.toml` | uv project + deps + ruff/pyright config |
| `.mise.toml` | task runner (`dev`, `ci`, `worker`, `beat`, `test`, `lint`) |
| `compose.yaml` | postgres + redis (+ later web/worker/beat) |
| `Dockerfile` | app image (used by worker/beat/web) |
| `manage.py` | Django entrypoint |
| `config/settings/base.py` | shared settings; `BRIEFING_LLM_BACKEND` default `claude-api` |
| `config/settings/local.py` | dev overrides; `BRIEFING_LLM_BACKEND=claude-subscription`, console email |
| `config/settings/production.py` | prod overrides |
| `config/settings/test.py` | `CELERY_TASK_ALWAYS_EAGER`, in-test mocks-friendly |
| `config/celery.py` | Celery app, autodiscover, beat schedule source |
| `config/__init__.py` | exposes `celery_app` |
| `config/urls.py` | minimal urlconf (admin only in Plan 1) |
| `briefing/models.py` | `Source`, `Item`, `Digest`, `Theme`, `ThemeItem` |
| `briefing/admin.py` | source/digest admin + "poll now" / "build digest" actions |
| `briefing/llm.py` | `LLMBackend` protocol + `get_backend()` + 3 backends |
| `briefing/sources/__init__.py` | `fetch_source(source)` dispatch + `RawItem` dataclass |
| `briefing/sources/rss.py` | RSS/Atom fetch via feedparser |
| `briefing/sources/readwise.py` | Readwise Reader API fetch |
| `briefing/tasks.py` | `poll_source`, `summarise_item`, `kick_off_digest`, `build_digest`, `send_digest`, `poll_all_sources` |
| `briefing/templates/briefing/digest_email.html` | email digest template |
| `tests/` | pytest-django tests mirroring the above |

---

## Task 1: Project scaffold (uv + Django + mise + Postgres)

**Files:**
- Create: `pyproject.toml`, `.mise.toml`, `compose.yaml`, `manage.py`
- Create: `config/__init__.py`, `config/settings/__init__.py`, `config/settings/base.py`, `config/settings/local.py`, `config/settings/test.py`, `config/urls.py`, `config/wsgi.py`
- Create: `briefing/__init__.py`, `briefing/apps.py`
- Create: `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "briefing"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "django>=6.0,<6.1",
    "celery>=5.4",
    "redis>=5.0",
    "psycopg[binary]>=3.2",
    "feedparser>=6.0",
    "anthropic>=0.40",
    "openai>=1.50",
    "requests>=2.32",
    "django-environ>=0.11",
]

[dependency-groups]
dev = [
    "ruff>=0.6",
    "pyright>=1.1.380",
    "pytest>=8.0",
    "pytest-django>=4.9",
    "responses>=0.25",
    "django-stubs>=5.1",        # PEP 561 ORM stubs so pyright can type-check models/querysets
]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
# ANN = flake8-annotations: require annotated function signatures.
select = ["E", "F", "I", "UP", "B", "DJ", "ANN"]

[tool.ruff.lint.per-file-ignores]
# Tests read better without return annotations on every test_* fn; migrations are generated.
"tests/**" = ["ANN"]
"**/migrations/**" = ["ANN", "E501"]

[tool.pyright]
include = ["briefing", "config", "tests"]
# "standard" is the pragmatic Django sweet spot: catches real type errors without drowning in
# ORM-manager generic noise. Bump to "strict" once the codebase settles if you want more.
typeCheckingMode = "standard"
stubPath = "typings"

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings.test"
python_files = ["test_*.py"]
addopts = "-q"
```

- [ ] **Step 2: Create `.mise.toml`**

```toml
[tools]
python = "3.12"
uv = "latest"

[env]
DJANGO_SETTINGS_MODULE = "config.settings.local"

[tasks.install]
run = "uv sync"

[tasks.dev]
run = "uv run python manage.py runserver"

[tasks.worker]
run = "uv run celery -A config worker -l info"

[tasks.beat]
run = "uv run celery -A config beat -l info"

[tasks.test]
run = "uv run pytest"

[tasks.lint]
run = ["uv run ruff check .", "uv run ruff format --check .", "uv run pyright"]

[tasks.ci]
depends = ["lint", "test"]
```

- [ ] **Step 3: Create `compose.yaml`** (Postgres + Redis only for Plan 1)

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: briefing
      POSTGRES_USER: briefing
      POSTGRES_PASSWORD: briefing
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
  redis:
    image: redis:7
    ports: ["6379:6379"]
volumes:
  pgdata:
```

- [ ] **Step 4: Create the settings package**

`config/settings/base.py`:

```python
import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env()

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-key")
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "briefing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ]},
    },
]

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://briefing:briefing@localhost:5432/briefing"),
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "static/"
TIME_ZONE = "Australia/Sydney"
USE_TZ = True

# Celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
CELERY_TASK_ALWAYS_EAGER = False

# LLM backend — committed default is the reproducible, key-based one.
BRIEFING_LLM_BACKEND = env("BRIEFING_LLM_BACKEND", default="claude-api")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
DEEPSEEK_API_KEY = env("DEEPSEEK_API_KEY", default="")
READWISE_TOKEN = env("READWISE_TOKEN", default="")

# Digest windows
BRIEFING_POLL_INTERVAL_MINUTES = 30
```

`config/settings/local.py`:

```python
from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Local-dev default: free-at-margin via the developer's logged-in Claude subscription.
BRIEFING_LLM_BACKEND = env("BRIEFING_LLM_BACKEND", default="claude-subscription")  # noqa: F405

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "briefing@localhost"
```

`config/settings/test.py`:

```python
from .base import *  # noqa: F403

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = False  # mirror prod: a failed chord-header task must not abort the chord
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
BRIEFING_LLM_BACKEND = "claude-api"  # tests inject a fake backend; this is just a valid default
```

`config/settings/__init__.py`: leave empty (selection is via `DJANGO_SETTINGS_MODULE`).

- [ ] **Step 5: Create `config/celery.py`, `config/__init__.py`, `config/urls.py`, `config/wsgi.py`, `manage.py`**

`config/celery.py`:

```python
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("briefing")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

`config/__init__.py`:

```python
from .celery import app as celery_app

__all__ = ["celery_app"]
```

`config/urls.py`:

```python
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
```

`config/wsgi.py`:

```python
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
application = get_wsgi_application()
```

`manage.py`:

```python
#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
```

- [ ] **Step 6: Create the `briefing` app package + `tests/conftest.py`**

`briefing/__init__.py`: empty. `briefing/apps.py`:

```python
from django.apps import AppConfig


class BriefingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "briefing"
```

`tests/__init__.py`: empty. `tests/conftest.py`:

```python
import pytest


@pytest.fixture
def db_access(db):
    """Alias so tests read intent: this test touches the database."""
    return db
```

- [ ] **Step 7: Install and verify the project boots**

Run: `mise run install && docker compose up -d postgres redis && uv run python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 8: Verify pytest collects (zero tests is fine)**

Run: `uv run pytest`
Expected: `no tests ran` (exit 5) — confirms Django settings + pytest-django wire up.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "scaffold briefing Django+Celery project with layered settings"
```

---

## Task 2: Celery sanity task (prove eager execution + autodiscover)

**Files:**
- Create: `briefing/tasks.py`
- Test: `tests/test_celery_wiring.py`

- [ ] **Step 1: Write the failing test**

`tests/test_celery_wiring.py`:

```python
from briefing.tasks import ping


def test_ping_runs_eagerly_and_returns_pong():
    result = ping.delay()
    assert result.get(timeout=1) == "pong"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_celery_wiring.py -v`
Expected: FAIL — `ImportError: cannot import name 'ping' from 'briefing.tasks'`.

- [ ] **Step 3: Write minimal implementation**

`briefing/tasks.py`:

```python
from celery import shared_task


@shared_task
def ping() -> str:
    return "pong"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_celery_wiring.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add briefing/tasks.py tests/test_celery_wiring.py
git commit -m "add Celery ping task and eager-execution test"
```

---

## Task 3: Data model + migrations

**Files:**
- Modify: `briefing/models.py` (create)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:

```python
import pytest
from django.db import IntegrityError

from briefing.models import Item, Source


def test_item_unique_per_source_external_id(db):
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    Item.objects.create(source=source, external_id="e1", url="https://x/1", content_hash="h1")
    with pytest.raises(IntegrityError):
        Item.objects.create(source=source, external_id="e1", url="https://x/1b", content_hash="h2")


def test_item_defaults_have_no_summary(db):
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    item = Item.objects.create(source=source, external_id="e2", url="https://x/2", content_hash="h3")
    assert item.summary == ""
    assert item.summarised_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ImportError` / `Source` has no `Kind`.

- [ ] **Step 3: Write the models**

`briefing/models.py`:

```python
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models


class Source(models.Model):
    class Kind(models.TextChoices):
        RSS = "rss", "RSS/Atom"
        READWISE = "readwise", "Readwise Reader"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    config = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)
    last_polled_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.config.get('url', self.pk)}"


class Item(models.Model):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="items")
    external_id = models.CharField(max_length=512)
    url = models.URLField(max_length=1024)
    title = models.CharField(max_length=512, blank=True)
    author = models.CharField(max_length=256, blank=True)
    raw_content = models.TextField(blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)
    content_hash = models.CharField(max_length=64)
    summary = models.TextField(blank=True)
    summarised_at = models.DateTimeField(null=True, blank=True)
    summarise_failed = models.BooleanField(default=False)
    search_vector = SearchVectorField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "external_id"], name="uniq_source_external_id"),
        ]
        indexes = [GinIndex(fields=["search_vector"], name="item_search_gin")]

    def __str__(self) -> str:
        return self.title or self.url


class Digest(models.Model):
    class Kind(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        SENT = "sent", "Sent"

    kind = models.CharField(max_length=8, choices=Kind.choices)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "period_start", "period_end"], name="uniq_digest_kind_period"
            ),
        ]


class Theme(models.Model):
    digest = models.ForeignKey(Digest, on_delete=models.CASCADE, related_name="themes")
    title = models.CharField(max_length=256)
    narrative = models.TextField()
    importance = models.IntegerField(default=0)

    class Meta:
        ordering = ["-importance"]


class ThemeItem(models.Model):
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE, related_name="theme_items")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="theme_items")
    rationale = models.TextField(blank=True)
```

- [ ] **Step 4: Make and run migrations, then the test**

Run: `uv run python manage.py makemigrations briefing && uv run pytest tests/test_models.py -v`
Expected: migration `0001_initial` created; both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add briefing/models.py briefing/migrations/ tests/test_models.py
git commit -m "add Source/Item/Digest/Theme/ThemeItem models with idempotency + FTS index"
```

---

## Task 4: LLM backend protocol + factory + Claude API backend

**Files:**
- Create: `briefing/llm.py`
- Test: `tests/test_llm.py`

The protocol returns plain data so tasks are backend-blind and tests need no live calls.

- [ ] **Step 1: Write the failing test**

`tests/test_llm.py`:

```python
from unittest.mock import MagicMock, patch

from briefing.llm import ClaudeAPIBackend, get_backend


def test_get_backend_reads_setting(settings):
    settings.BRIEFING_LLM_BACKEND = "claude-api"
    settings.ANTHROPIC_API_KEY = "sk-test"
    assert isinstance(get_backend(), ClaudeAPIBackend)


def test_get_backend_unknown_raises(settings):
    settings.BRIEFING_LLM_BACKEND = "nope"
    try:
        get_backend()
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "nope" in str(exc)


@patch("briefing.llm.anthropic.Anthropic")
def test_claude_api_condense_returns_text(mock_anthropic):
    client = mock_anthropic.return_value
    client.messages.create.return_value = MagicMock(content=[MagicMock(text="short summary")])
    backend = ClaudeAPIBackend(api_key="sk-test")
    assert backend.condense("a long article body") == "short summary"


@patch("briefing.llm.anthropic.Anthropic")
def test_claude_api_synthesise_parses_themes(mock_anthropic):
    client = mock_anthropic.return_value
    payload = '{"themes": [{"title": "AI", "narrative": "n", "importance": 5, ' \
              '"items": [{"item_id": 1, "rationale": "r"}]}]}'
    client.messages.create.return_value = MagicMock(content=[MagicMock(text=payload)])
    backend = ClaudeAPIBackend(api_key="sk-test")
    themes = backend.synthesise([{"item_id": 1, "title": "t", "summary": "s"}])
    assert themes[0]["title"] == "AI"
    assert themes[0]["items"][0]["item_id"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'briefing.llm'`.

- [ ] **Step 3: Write the protocol, factory, and Claude API backend**

`briefing/llm.py`:

```python
import json
from typing import Protocol

import anthropic
from django.conf import settings

CONDENSE_MODEL = "claude-haiku-4-5"
SYNTHESIS_MODEL = "claude-sonnet-4-6"

_CONDENSE_PROMPT = "Condense the following into 2-3 plain sentences. Text:\n\n{text}"
_SYNTHESIS_PROMPT = (
    "You are given content items as JSON. Identify the 3-5 cross-source themes that matter most. "
    "Return ONLY JSON of the form "
    '{{"themes": [{{"title": str, "narrative": str, "importance": int, '
    '"items": [{{"item_id": int, "rationale": str}}]}}]}}. Items:\n\n{items}'
)


class LLMBackend(Protocol):
    def condense(self, text: str) -> str: ...
    def synthesise(self, items: list[dict]) -> list[dict]: ...


def get_backend() -> LLMBackend:
    name = settings.BRIEFING_LLM_BACKEND
    if name == "claude-api":
        return ClaudeAPIBackend(api_key=settings.ANTHROPIC_API_KEY)
    if name == "claude-subscription":
        from briefing.llm_subscription import ClaudeSubscriptionBackend

        return ClaudeSubscriptionBackend()
    if name == "deepseek":
        from briefing.llm_deepseek import DeepSeekBackend

        return DeepSeekBackend(api_key=settings.DEEPSEEK_API_KEY)
    raise ValueError(f"Unknown BRIEFING_LLM_BACKEND: {name!r}")


class ClaudeAPIBackend:
    def __init__(self, api_key: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)

    def condense(self, text: str) -> str:
        resp = self._client.messages.create(
            model=CONDENSE_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": _CONDENSE_PROMPT.format(text=text)}],
        )
        return resp.content[0].text.strip()

    def synthesise(self, items: list[dict]) -> list[dict]:
        resp = self._client.messages.create(
            model=SYNTHESIS_MODEL,
            max_tokens=2000,
            messages=[
                {"role": "user", "content": _SYNTHESIS_PROMPT.format(items=json.dumps(items))}
            ],
        )
        return _parse_themes(resp.content[0].text)


def _parse_themes(raw: str) -> list[dict]:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in synthesis response: {raw[:200]!r}")
    return json.loads(raw[start : end + 1])["themes"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_llm.py -v`
Expected: all four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add briefing/llm.py tests/test_llm.py
git commit -m "add LLMBackend protocol, get_backend factory, and Claude API backend"
```

---

## Task 5: Claude subscription + DeepSeek backends

**Files:**
- Create: `briefing/llm_subscription.py`, `briefing/llm_deepseek.py`
- Test: `tests/test_llm_subscription.py`, `tests/test_llm_deepseek.py`

Both reuse `_parse_themes` and the shared prompts from `briefing/llm.py` (DRY).

- [ ] **Step 1: Write the failing tests**

`tests/test_llm_subscription.py`:

```python
import json
from unittest.mock import patch

from briefing.llm_subscription import ClaudeSubscriptionBackend


@patch("briefing.llm_subscription.subprocess.run")
def test_subscription_condense_shells_out_to_claude(mock_run):
    mock_run.return_value.stdout = json.dumps({"result": "a short summary"})
    mock_run.return_value.returncode = 0
    backend = ClaudeSubscriptionBackend()
    assert backend.condense("body text") == "a short summary"
    args = mock_run.call_args.args[0]
    assert args[0] == "claude"
    assert "--output-format" in args and "json" in args
```

`tests/test_llm_deepseek.py`:

```python
from unittest.mock import MagicMock, patch

from briefing.llm_deepseek import DeepSeekBackend


@patch("briefing.llm_deepseek.openai.OpenAI")
def test_deepseek_uses_openai_sdk_with_base_url(mock_openai):
    client = mock_openai.return_value
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="short summary"))]
    )
    backend = DeepSeekBackend(api_key="dk-test")
    assert backend.condense("body") == "short summary"
    assert mock_openai.call_args.kwargs["base_url"] == "https://api.deepseek.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_subscription.py tests/test_llm_deepseek.py -v`
Expected: FAIL — modules not found.

- [ ] **Step 3: Write the backends**

`briefing/llm_subscription.py`:

```python
import json
import subprocess

from briefing.llm import _SYNTHESIS_PROMPT, _parse_themes


class ClaudeSubscriptionBackend:
    """Shells out to the logged-in `claude` CLI. Local-dev default; free-at-margin."""

    def condense(self, text: str) -> str:
        return self._run(f"Condense the following into 2-3 plain sentences. Text:\n\n{text}")

    def synthesise(self, items: list[dict]) -> list[dict]:
        return _parse_themes(self._run(_SYNTHESIS_PROMPT.format(items=json.dumps(items))))

    def _run(self, prompt: str) -> str:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        return json.loads(proc.stdout)["result"].strip()
```

`briefing/llm_deepseek.py`:

```python
import json

import openai

from briefing.llm import _SYNTHESIS_PROMPT, _parse_themes

CONDENSE_MODEL = "deepseek-chat"
SYNTHESIS_MODEL = "deepseek-chat"


class DeepSeekBackend:
    def __init__(self, api_key: str) -> None:
        self._client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    def condense(self, text: str) -> str:
        return self._chat(CONDENSE_MODEL, f"Condense into 2-3 plain sentences:\n\n{text}")

    def synthesise(self, items: list[dict]) -> list[dict]:
        return _parse_themes(self._chat(SYNTHESIS_MODEL, _SYNTHESIS_PROMPT.format(items=json.dumps(items))))

    def _chat(self, model: str, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}]
        )
        return resp.choices[0].message.content.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_subscription.py tests/test_llm_deepseek.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add briefing/llm_subscription.py briefing/llm_deepseek.py tests/test_llm_subscription.py tests/test_llm_deepseek.py
git commit -m "add Claude-subscription (subprocess) and DeepSeek (openai SDK) LLM backends"
```

---

## Task 6: Source fetchers (RSS + Readwise) returning normalised `RawItem`s

**Files:**
- Create: `briefing/sources/__init__.py`, `briefing/sources/rss.py`, `briefing/sources/readwise.py`
- Test: `tests/test_sources.py`
- Fixture: `tests/fixtures/sample_feed.xml`

- [ ] **Step 1: Create the RSS fixture**

`tests/fixtures/sample_feed.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Demo</title>
  <item><guid>post-1</guid><link>https://demo/1</link><title>First</title>
    <author>alice</author><description>Body one</description></item>
  <item><guid>post-2</guid><link>https://demo/2</link><title>Second</title>
    <author>bob</author><description>Body two</description></item>
</channel></rss>
```

- [ ] **Step 2: Write the failing test**

`tests/test_sources.py`:

```python
from pathlib import Path

import responses

from briefing.sources import RawItem
from briefing.sources.readwise import fetch as fetch_readwise
from briefing.sources.rss import fetch as fetch_rss

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


@responses.activate
def test_rss_fetch_normalises_entries():
    responses.add(responses.GET, "https://demo/feed", body=FIXTURE.read_text(), status=200)
    items = fetch_rss({"url": "https://demo/feed"})
    assert len(items) == 2
    assert items[0] == RawItem(
        external_id="post-1", url="https://demo/1", title="First", author="alice",
        raw_content="Body one",
    )


@responses.activate
def test_readwise_fetch_normalises_documents():
    responses.add(
        responses.GET,
        "https://readwise.io/api/v3/list/",
        json={"results": [{"id": "d1", "url": "https://r/1", "title": "Doc",
                           "author": "carol", "summary": "sum", "content": "full"}],
              "nextPageCursor": None},
        status=200,
    )
    items = fetch_readwise({"token": "rw-test"})
    assert items[0].external_id == "d1"
    assert items[0].raw_content == "full"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_sources.py -v`
Expected: FAIL — `briefing.sources` not found.

- [ ] **Step 4: Write the source modules**

`briefing/sources/__init__.py`:

```python
from dataclasses import dataclass

from briefing.models import Source


@dataclass(frozen=True)
class RawItem:
    external_id: str
    url: str
    title: str
    author: str
    raw_content: str


def fetch_source(source: Source) -> list[RawItem]:
    from briefing.sources import readwise, rss

    if source.kind == Source.Kind.RSS:
        return rss.fetch(source.config)
    if source.kind == Source.Kind.READWISE:
        return readwise.fetch(source.config)
    raise ValueError(f"Unknown source kind: {source.kind!r}")
```

`briefing/sources/rss.py`:

```python
import feedparser
import requests

from briefing.sources import RawItem

TIMEOUT_SECONDS = 30


def fetch(config: dict) -> list[RawItem]:
    resp = requests.get(config["url"], timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    return [
        RawItem(
            external_id=entry.get("id") or entry.get("link", ""),
            url=entry.get("link", ""),
            title=entry.get("title", ""),
            author=entry.get("author", ""),
            raw_content=entry.get("summary", ""),
        )
        for entry in parsed.entries
    ]
```

`briefing/sources/readwise.py`:

```python
import requests

from briefing.sources import RawItem

LIST_URL = "https://readwise.io/api/v3/list/"
TIMEOUT_SECONDS = 30


def fetch(config: dict) -> list[RawItem]:
    resp = requests.get(
        LIST_URL,
        headers={"Authorization": f"Token {config['token']}"},
        timeout=TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return [
        RawItem(
            external_id=str(doc["id"]),
            url=doc.get("url", ""),
            title=doc.get("title", ""),
            author=doc.get("author", ""),
            raw_content=doc.get("content") or doc.get("summary", ""),
        )
        for doc in resp.json().get("results", [])
    ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_sources.py -v`
Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add briefing/sources/ tests/test_sources.py tests/fixtures/sample_feed.xml
git commit -m "add RSS and Readwise source fetchers returning normalised RawItems"
```

---

## Task 7: `poll_source` — idempotent upsert by `content_hash`

This task carries the **re-summarise-on-content-change policy**: a re-poll of unchanged content is a no-op; changed content clears the stale summary and re-queues.

**Files:**
- Modify: `briefing/tasks.py`
- Test: `tests/test_poll_source.py`

- [ ] **Step 1: Write the failing test (idempotency + content-change)**

`tests/test_poll_source.py`:

```python
from unittest.mock import patch

from briefing.models import Item, Source
from briefing.sources import RawItem
from briefing.tasks import poll_source


def _raw(content: str) -> RawItem:
    return RawItem(external_id="e1", url="https://x/1", title="T", author="a", raw_content=content)


def test_poll_is_idempotent_on_repeat(db):
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    with patch("briefing.tasks.fetch_source", return_value=[_raw("body")]):
        poll_source(source.id)
        poll_source(source.id)
    assert Item.objects.filter(source=source).count() == 1


def test_poll_resummarises_on_content_change(db):
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    with patch("briefing.tasks.fetch_source", return_value=[_raw("body")]):
        poll_source(source.id)
    item = Item.objects.get(source=source)
    item.summary, item.summarise_failed = "old summary", True
    item.save(update_fields=["summary", "summarise_failed"])

    with patch("briefing.tasks.fetch_source", return_value=[_raw("CHANGED body")]):
        poll_source(source.id)

    item.refresh_from_db()
    assert item.raw_content == "CHANGED body"
    assert item.summary == ""
    assert item.summarise_failed is False
    assert item.summarised_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_poll_source.py -v`
Expected: FAIL — `cannot import name 'poll_source'`.

- [ ] **Step 3: Implement `poll_source` + `content_hash` helper**

Append to `briefing/tasks.py`:

```python
import hashlib

from celery import shared_task
from django.utils import timezone

from briefing.models import Item, Source
from briefing.sources import fetch_source


def _content_hash(raw_content: str) -> str:
    return hashlib.sha256(raw_content.encode("utf-8")).hexdigest()


@shared_task(autoretry_for=(Exception,), max_retries=3, retry_backoff=True)
def poll_source(source_id: int) -> list[int]:
    source = Source.objects.get(id=source_id)
    touched_ids: list[int] = []
    for raw in fetch_source(source):
        digest = _content_hash(raw.raw_content)
        item, created = Item.objects.get_or_create(
            source=source,
            external_id=raw.external_id,
            defaults={
                "url": raw.url, "title": raw.title, "author": raw.author,
                "raw_content": raw.raw_content, "content_hash": digest,
            },
        )
        if created:
            touched_ids.append(item.id)
        elif item.content_hash != digest:
            item.url, item.title, item.author = raw.url, raw.title, raw.author
            item.raw_content, item.content_hash = raw.raw_content, digest
            item.summary, item.summarised_at, item.summarise_failed = "", None, False
            item.save(update_fields=[
                "url", "title", "author", "raw_content", "content_hash",
                "summary", "summarised_at", "summarise_failed",
            ])
            touched_ids.append(item.id)
    source.last_polled_at = timezone.now()
    source.save(update_fields=["last_polled_at"])
    return touched_ids
```

Note: the existing `ping` task and any earlier imports stay; do not duplicate the `from celery import shared_task` import — keep one.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_poll_source.py -v`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add briefing/tasks.py tests/test_poll_source.py
git commit -m "add idempotent poll_source with re-summarise-on-content-change"
```

---

## Task 8: `summarise_item` — partial-success (a dead item never aborts the chord)

**Files:**
- Modify: `briefing/tasks.py`
- Test: `tests/test_summarise_item.py`

- [ ] **Step 1: Write the failing test**

`tests/test_summarise_item.py`:

```python
from unittest.mock import MagicMock, patch

from briefing.models import Item, Source
from briefing.tasks import summarise_item


def _item(db, summary=""):
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    return Item.objects.create(
        source=source, external_id="e1", url="https://x/1", content_hash="h1",
        raw_content="body", summary=summary,
    )


def test_summarise_sets_summary(db):
    item = _item(db)
    backend = MagicMock()
    backend.condense.return_value = "short summary"
    with patch("briefing.tasks.get_backend", return_value=backend):
        summarise_item(item.id)
    item.refresh_from_db()
    assert item.summary == "short summary"
    assert item.summarised_at is not None


def test_summarise_skips_already_summarised(db):
    item = _item(db, summary="done")
    backend = MagicMock()
    with patch("briefing.tasks.get_backend", return_value=backend):
        summarise_item(item.id)
    backend.condense.assert_not_called()


def test_summarise_failure_is_swallowed_so_chord_survives(db):
    item = _item(db)
    backend = MagicMock()
    backend.condense.side_effect = RuntimeError("LLM down")
    with patch("briefing.tasks.get_backend", return_value=backend):
        summarise_item.retry = MagicMock(side_effect=Exception("retried"))
        # final attempt: exception must NOT propagate out of the task body
        result = summarise_item.run(item.id, _final_attempt=True)
    item.refresh_from_db()
    assert item.summarise_failed is True
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_summarise_item.py -v`
Expected: FAIL — `cannot import name 'summarise_item'`.

- [ ] **Step 3: Implement `summarise_item`**

Append to `briefing/tasks.py`:

```python
from briefing.llm import get_backend


@shared_task(bind=True, max_retries=3, retry_backoff=True)
def summarise_item(self, item_id: int, _final_attempt: bool = False) -> int | None:
    item = Item.objects.get(id=item_id)
    if item.summarised_at is not None:
        return item.id
    try:
        summary = get_backend().condense(item.raw_content)
    except Exception as exc:  # noqa: BLE001 — see policy below
        if _final_attempt or self.request.retries >= self.max_retries:
            # Partial-success policy: mark the item, return None, and let the chord proceed.
            Item.objects.filter(id=item_id).update(summarise_failed=True)
            return None
        raise self.retry(exc=exc)
    item.summary, item.summarised_at, item.summarise_failed = summary, timezone.now(), False
    item.save(update_fields=["summary", "summarised_at", "summarise_failed"])
    return item.id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_summarise_item.py -v`
Expected: all three PASS.

- [ ] **Step 5: Commit**

```bash
git add briefing/tasks.py tests/test_summarise_item.py
git commit -m "add summarise_item with partial-success policy (failed item never aborts chord)"
```

---

## Task 9: `build_digest` chord callback + `kick_off_digest` + `send_digest`

**Files:**
- Modify: `briefing/tasks.py`
- Create: `briefing/templates/briefing/digest_email.html`
- Test: `tests/test_build_digest.py`, `tests/test_send_digest.py`

- [ ] **Step 1: Write the failing test for `build_digest` (aggregation + idempotency)**

`tests/test_build_digest.py`:

```python
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from briefing.models import Digest, Item, Source, ThemeItem
from briefing.tasks import build_digest


def _summarised_item(source, ext, summary):
    return Item.objects.create(
        source=source, external_id=ext, url=f"https://x/{ext}", content_hash=ext,
        title=f"T{ext}", summary=summary, summarised_at=timezone.now(),
    )


def test_build_digest_synthesises_and_persists(db):
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    item = _summarised_item(source, "e1", "summary one")
    start, end = timezone.now() - timedelta(days=1), timezone.now() + timedelta(minutes=1)
    fake_themes = [{"title": "Theme A", "narrative": "n", "importance": 9,
                    "items": [{"item_id": item.id, "rationale": "central"}]}]
    with patch("briefing.tasks.get_backend") as get_backend, \
         patch("briefing.tasks.send_digest.delay") as send:
        get_backend.return_value.synthesise.return_value = fake_themes
        build_digest("daily", start.isoformat(), end.isoformat())

    digest = Digest.objects.get(kind="daily")
    assert digest.status == Digest.Status.READY
    assert digest.themes.get().title == "Theme A"
    assert ThemeItem.objects.get().item_id == item.id
    send.assert_called_once_with(digest.id)


def test_build_digest_is_idempotent_per_period(db):
    start, end = timezone.now() - timedelta(days=1), timezone.now()
    with patch("briefing.tasks.get_backend") as get_backend, \
         patch("briefing.tasks.send_digest.delay"):
        get_backend.return_value.synthesise.return_value = []
        build_digest("daily", start.isoformat(), end.isoformat())
        build_digest("daily", start.isoformat(), end.isoformat())
    assert Digest.objects.filter(kind="daily").count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_build_digest.py -v`
Expected: FAIL — `cannot import name 'build_digest'`.

- [ ] **Step 3: Implement `kick_off_digest`, `build_digest`, `send_digest`**

Append to `briefing/tasks.py`:

```python
from datetime import datetime

from celery import chord
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from briefing.models import Digest, Theme, ThemeItem


@shared_task
def kick_off_digest(kind: str, period_start: str, period_end: str) -> None:
    start, end = datetime.fromisoformat(period_start), datetime.fromisoformat(period_end)
    pending = Item.objects.filter(
        fetched_at__gte=start, fetched_at__lt=end, summarised_at__isnull=True
    ).values_list("id", flat=True)
    callback = build_digest.si(kind, period_start, period_end)
    if not pending:
        callback.delay()
        return
    chord((summarise_item.s(item_id) for item_id in pending), callback).delay()


@shared_task
def build_digest(kind: str, period_start: str, period_end: str) -> int:
    start, end = datetime.fromisoformat(period_start), datetime.fromisoformat(period_end)
    digest, created = Digest.objects.get_or_create(
        kind=kind, period_start=start, period_end=end
    )
    if not created and digest.status != Digest.Status.PENDING:
        return digest.id

    items = list(
        Item.objects.filter(
            fetched_at__gte=start, fetched_at__lt=end, summarised_at__isnull=False
        ).exclude(summary="")
    )
    payload = [{"item_id": i.id, "title": i.title, "summary": i.summary} for i in items]
    by_id = {i.id: i for i in items}

    for theme_data in get_backend().synthesise(payload):
        theme = Theme.objects.create(
            digest=digest, title=theme_data["title"],
            narrative=theme_data["narrative"], importance=theme_data.get("importance", 0),
        )
        for link in theme_data.get("items", []):
            item = by_id.get(link["item_id"])
            if item is not None:
                ThemeItem.objects.create(theme=theme, item=item, rationale=link.get("rationale", ""))

    digest.status = Digest.Status.READY
    digest.save(update_fields=["status"])
    send_digest.delay(digest.id)
    return digest.id


@shared_task
def send_digest(digest_id: int) -> None:
    digest = Digest.objects.get(id=digest_id)
    html = render_to_string("briefing/digest_email.html", {"digest": digest})
    message = EmailMultiAlternatives(
        subject=f"{digest.get_kind_display()} briefing",
        body="Open in an HTML-capable client.",
        to=["me@localhost"],
    )
    message.attach_alternative(html, "text/html")
    message.send()
    digest.status = Digest.Status.SENT
    digest.save(update_fields=["status"])
```

- [ ] **Step 4: Create the email template**

`briefing/templates/briefing/digest_email.html`:

```html
<!doctype html>
<html><body>
  <h1>{{ digest.get_kind_display }} briefing</h1>
  <p>{{ digest.period_start|date:"j M" }} – {{ digest.period_end|date:"j M" }}</p>
  {% for theme in digest.themes.all %}
    <section>
      <h2>{{ theme.title }}</h2>
      <p>{{ theme.narrative }}</p>
      <ul>
        {% for link in theme.theme_items.all %}
          <li><a href="{{ link.item.url }}">{{ link.item.title }}</a> — {{ link.rationale }}</li>
        {% endfor %}
      </ul>
    </section>
  {% empty %}
    <p>No themes this period.</p>
  {% endfor %}
</body></html>
```

- [ ] **Step 5: Write the `send_digest` test**

`tests/test_send_digest.py`:

```python
from django.core import mail
from django.utils import timezone

from briefing.models import Digest, Theme
from briefing.tasks import send_digest


def test_send_digest_renders_html_email(db):
    digest = Digest.objects.create(
        kind="daily", period_start=timezone.now(), period_end=timezone.now(),
        status=Digest.Status.READY,
    )
    Theme.objects.create(digest=digest, title="Big Theme", narrative="why", importance=5)
    send_digest(digest.id)
    assert len(mail.outbox) == 1
    assert "Big Theme" in mail.outbox[0].alternatives[0][0]
    digest.refresh_from_db()
    assert digest.status == Digest.Status.SENT
```

- [ ] **Step 6: Run all the digest tests**

Run: `uv run pytest tests/test_build_digest.py tests/test_send_digest.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add briefing/tasks.py briefing/templates/ tests/test_build_digest.py tests/test_send_digest.py
git commit -m "add kick_off_digest chord, build_digest synthesis, and send_digest email"
```

---

## Task 10: Beat schedule + admin (manage sources, trigger runs)

**Files:**
- Modify: `briefing/tasks.py` (add `poll_all_sources`), `config/settings/base.py` (beat schedule)
- Create: `briefing/admin.py`
- Test: `tests/test_poll_all_sources.py`, `tests/test_admin_actions.py`

- [ ] **Step 1: Write the failing test for `poll_all_sources` fan-out**

`tests/test_poll_all_sources.py`:

```python
from unittest.mock import patch

from briefing.models import Source
from briefing.tasks import poll_all_sources


def test_poll_all_sources_fans_out_to_enabled_only(db):
    enabled = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://y/feed"}, enabled=False)
    with patch("briefing.tasks.poll_source.delay") as delay:
        poll_all_sources()
    delay.assert_called_once_with(enabled.id)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_poll_all_sources.py -v`
Expected: FAIL — `cannot import name 'poll_all_sources'`.

- [ ] **Step 3: Add `poll_all_sources` and the beat schedule**

Append to `briefing/tasks.py`:

```python
@shared_task
def poll_all_sources() -> None:
    for source_id in Source.objects.filter(enabled=True).values_list("id", flat=True):
        poll_source.delay(source_id)
```

Append to `config/settings/base.py`:

```python
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    "poll-all-sources": {
        "task": "briefing.tasks.poll_all_sources",
        "schedule": BRIEFING_POLL_INTERVAL_MINUTES * 60,
    },
    "daily-digest": {
        "task": "briefing.tasks.kick_off_digest",
        "schedule": crontab(hour=7, minute=0),
        "args": ("daily", "{{period_start}}", "{{period_end}}"),
    },
}
```

Note for the implementer: Celery Beat cannot compute a rolling window in static config. Replace the `daily-digest` entry's static args with a tiny wrapper task `kick_off_daily` that computes `period_start=now-24h, period_end=now` and calls `kick_off_digest`. Add it now:

```python
# briefing/tasks.py
from datetime import timedelta


@shared_task
def kick_off_daily() -> None:
    end = timezone.now()
    kick_off_digest("daily", (end - timedelta(days=1)).isoformat(), end.isoformat())
```

And fix the schedule entry to `"task": "briefing.tasks.kick_off_daily"` with no `args`.

- [ ] **Step 4: Write the admin action test**

`tests/test_admin_actions.py`:

```python
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite

from briefing.admin import SourceAdmin
from briefing.models import Source


def test_poll_now_action_enqueues_poll(db):
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    admin = SourceAdmin(Source, AdminSite())
    with patch("briefing.admin.poll_source.delay") as delay:
        admin.poll_now(request=None, queryset=Source.objects.all())
    delay.assert_called_once_with(source.id)
```

- [ ] **Step 5: Write `briefing/admin.py`**

```python
from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from briefing.models import Digest, Item, Source, Theme
from briefing.tasks import poll_source


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("kind", "config", "enabled", "last_polled_at")
    actions = ["poll_now"]

    @admin.action(description="Poll selected sources now")
    def poll_now(self, request: HttpRequest | None, queryset: QuerySet[Source]) -> None:
        for source in queryset:
            poll_source.delay(source.id)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("title", "source", "summarised_at", "summarise_failed")
    list_filter = ("source", "summarise_failed")


@admin.register(Digest)
class DigestAdmin(admin.ModelAdmin):
    list_display = ("kind", "period_start", "period_end", "status")


admin.site.register(Theme)
```

- [ ] **Step 6: Run both tests**

Run: `uv run pytest tests/test_poll_all_sources.py tests/test_admin_actions.py -v`
Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add briefing/tasks.py briefing/admin.py config/settings/base.py tests/test_poll_all_sources.py tests/test_admin_actions.py
git commit -m "add beat schedule, poll_all_sources fan-out, and admin with poll-now action"
```

---

## Task 11: Full pipeline integration test + CI green

**Files:**
- Test: `tests/test_pipeline_integration.py`

- [ ] **Step 1: Write the end-to-end test (eager, mocked LLM + HTTP)**

`tests/test_pipeline_integration.py`:

```python
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import responses
from django.core import mail
from django.utils import timezone

from briefing.models import Digest, Item, Source
from briefing.tasks import kick_off_digest, poll_source

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


@responses.activate
def test_full_pipeline_poll_summarise_digest_email(db):
    responses.add(responses.GET, "https://demo/feed", body=FIXTURE.read_text(), status=200)
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://demo/feed"})

    poll_source(source.id)
    poll_source(source.id)  # second poll: no duplicates
    assert Item.objects.filter(source=source).count() == 2

    backend = MagicMock()
    backend.condense.return_value = "a summary"
    backend.synthesise.return_value = [
        {"title": "The Theme", "narrative": "why it matters", "importance": 8, "items": []}
    ]
    start, end = timezone.now() - timedelta(hours=1), timezone.now() + timedelta(hours=1)
    with patch("briefing.tasks.get_backend", return_value=backend):
        kick_off_digest("daily", start.isoformat(), end.isoformat())

    digest = Digest.objects.get(kind="daily")
    assert digest.status == Digest.Status.SENT
    assert digest.themes.get().title == "The Theme"
    assert len(mail.outbox) == 1
    assert "The Theme" in mail.outbox[0].alternatives[0][0]
```

- [ ] **Step 2: Run the integration test**

Run: `uv run pytest tests/test_pipeline_integration.py -v`
Expected: PASS — confirms poll idempotency → chord summarise → synthesis → email in one eager run.

- [ ] **Step 3: Run the whole suite + lint (full CI)**

Run: `mise run ci`
Expected: ruff clean, ruff format clean, pyright clean, all pytest tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_pipeline_integration.py
git commit -m "add end-to-end pipeline integration test"
```

---

## Task 12: Manual smoke verification (real services, console email)

No code — this is the spec's manual verification, run once to confirm the wiring outside `task_always_eager`.

- [ ] **Step 1: Bring up infra + workers**

```bash
docker compose up -d postgres redis
uv run python manage.py migrate
uv run python manage.py createsuperuser   # for admin access
mise run worker   # terminal 2
mise run beat     # terminal 3 (optional for smoke)
mise run dev      # terminal 4
```

- [ ] **Step 2: Add an RSS source in admin and poll it**

Open `http://localhost:8000/admin/`, add a `Source` (kind=RSS, config `{"url": "<a real feed>"}`), select it, run **"Poll selected sources now"**. Confirm `Item`s appear; run the action again and confirm **no duplicates** (count unchanged).

- [ ] **Step 3: Drive a digest from a shell**

```bash
uv run python manage.py shell -c "
from datetime import timedelta; from django.utils import timezone
from briefing.tasks import kick_off_digest
end = timezone.now(); start = end - timedelta(days=1)
kick_off_digest.delay('daily', start.isoformat(), end.isoformat())
"
```

Watch the worker log: `summarise_item` runs per item, then `build_digest`, then `send_digest` prints the HTML email to the console. With local-dev settings this uses the `claude-subscription` backend via `claude -p` — confirm it condenses using your logged-in session.

- [ ] **Step 4: Prove the LLM abstraction**

Re-run Step 3 with `BRIEFING_LLM_BACKEND=claude-api uv run celery -A config worker -l info` (needs `ANTHROPIC_API_KEY`). Same pipeline, different backend — confirms the protocol boundary.

- [ ] **Step 5: Commit any config tweaks discovered during smoke**

```bash
git add -A && git commit -m "smoke-test fixups"   # only if needed
```

---

## Self-Review (completed against the spec)

- **Spec coverage:** RSS + Readwise ingest (Task 6) ✓; per-item condense (Task 8) ✓; cross-source theme synthesis (Task 9) ✓; daily/weekly digest (Tasks 9–10; weekly = add a `kick_off_weekly` mirroring `kick_off_daily` + a beat entry — noted below) ✓; email delivery (Task 9) ✓; three LLM backends behind one protocol (Tasks 4–5) ✓; Django admin for sources + re-trigger (Task 10) ✓; layered-settings backend default (Task 1) ✓; content_hash idempotency + re-summarise policy (Task 7) ✓; chord partial-success (Task 8) ✓; CI = ruff+pyright+pytest with mocked LLM/HTTP and eager Celery (Task 11) ✓.
- **Deferred to Plan 2 (web surface):** PWA manifest+SW, dashboard/archive views, Postgres FTS *search UI* (the `search_vector` column + GIN index + population are modelled here; the query UI is Plan 2), allauth GitHub login, weekly-digest beat entry can also land in Plan 2 alongside the views. The `search_vector` is created but not yet populated — Plan 2 adds a `.update(search_vector=SearchVector("title", "summary"))` step after summarise and the search view.
- **Placeholder scan:** none — every code step is complete. The one templated beat entry in Task 10 Step 3 is explicitly replaced with `kick_off_daily` in the same step.
- **Type consistency:** `RawItem` fields match across Tasks 6–7; `get_backend()` signature matches Tasks 4/8/9; theme dict shape (`title`/`narrative`/`importance`/`items[].item_id`/`items[].rationale`) is identical in `llm.py`, `build_digest`, and all tests.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-15-cross-source-briefing-pipeline.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?** (And: want me to write **Plan 2 — the web/PWA/FTS/allauth surface** now, or after the pipeline is built?)
