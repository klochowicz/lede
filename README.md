# lede

**Surface the few things that matter across everything you read — don't bury the lede.**

`lede` pulls items from your content sources on a schedule, condenses each with an LLM, then
synthesises a whole window of them into a small set of **cross-source themes** — *"the 3–5 things
that matter this week, and why"* — delivered as an email digest and a mobile-friendly archive.

The wedge: tools like Readwise summarise *individual* items on demand. `lede` produces a scheduled
*cross-source synthesis* — the connective tissue between sources, not a per-item TL;DR.

---

## Why Django **and** Celery

This is a portfolio project, so the architecture is the point. The split is deliberate and the
README is honest about it:

- **Django** owns the read side: the Postgres data model, the dashboard + digest archive, Postgres
  full-text search, `django-allauth` GitHub login, the email templates, and a thin admin for
  managing sources. CQRS-ish — views are read-only over the same tables the pipeline writes.
- **Celery** owns the write side: the **scheduled, fan-out, chorded, retried** pipeline. Django 6
  shipped `django.tasks` — a task *enqueue* abstraction — but it is not a scheduler. This workload
  needs three things `django.tasks` doesn't provide: a **scheduler** (Beat), a **workflow canvas**
  (the `chord` that aggregates N per-item summaries into one synthesis), and **serious retry +
  rate-limiting** for flaky LLM/HTTP I/O. That orchestrated pipeline is what Celery is *for*.

## Architecture

```
Celery Beat ──poll (fan-out, retried)──> Items in Postgres
                                            │
              summarise_item (per item, LLM, retried) ── chord ──┐
                                                                 ▼
            build_digest (window aggregate → LLM theme synthesis → persist)
                                                                 │
                                          ┌──────────────────────┴──────────────┐
                                          ▼                                      ▼
                                  send_digest (email)        Django views / PWA (Postgres + FTS)
```

A failed `summarise_item` is designed to **degrade, not abort**: it marks the item and returns,
so one dead source never sinks the whole digest (the chord still fires).

## Data model

`Source` → `Item` (idempotent on `(source, external_id)` via a `content_hash`; FTS `search_vector`,
GIN-indexed) → `Digest` (idempotent per `(kind, period)`) → `Theme` → `ThemeItem` (per-link rationale).

## LLM layer — provider-agnostic

A small `LLMBackend` protocol (`condense`, `synthesise`) hides three interchangeable backends, chosen
per environment via `BRIEFING_LLM_BACKEND`:

| Backend | Default in | Notes |
|---|---|---|
| **Claude API** | committed / prod | Reproducible — anyone runs it with their own `ANTHROPIC_API_KEY`. |
| **Claude subscription** | local dev | Free-at-margin: shells out to a logged-in `claude -p`. |
| **DeepSeek** | opt-in | Uses the `openai` SDK at the DeepSeek base URL. |

Untrusted feed content is wrapped in delimiters and the model is told to treat it as data, not
instructions (prompt-injection mitigation); the parsed theme JSON is validated and item ids are
coerced defensively.

## Stack

Python 3.12 · Django 6 · Celery 5 · Postgres 16 · Redis · `feedparser` · `anthropic` / `openai` ·
`django-allauth`. Tooling: **uv** (deps) · **mise** (tasks) · **ruff** · **mypy + django-stubs** ·
**pytest-django**.

## Running it

```sh
mise run install                       # uv sync
docker compose up -d postgres redis
uv run python manage.py migrate
uv run python manage.py createsuperuser
mise run worker                        # Celery worker          (terminal 2)
mise run beat                          # Celery Beat scheduler  (terminal 3)
mise run dev                           # Django dev server      (terminal 4)
```

Then add an RSS `Source` in `/admin/`, trigger a poll, and drive a digest. In dev the digest email
renders to the console.

**One-command smoke** — seed sample items and run summarise → synthesis → email through the
configured backend (great for a live demo of any of the three LLM backends):

```sh
BRIEFING_LLM_BACKEND=claude-subscription uv run python manage.py smoke_digest
```

### Auth & access

GitHub OAuth is the only way in (local password accounts are disabled). To enable login:

1. Create a GitHub OAuth app — callback URL `http://localhost:8000/accounts/github/login/callback/`.
2. Set `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`.
3. Lock the app to yourself: `BRIEFING_ALLOWED_GITHUB_LOGINS=<your-github-username>` (empty = open).

## Tests & CI

```sh
mise run ci   # ruff + ruff format --check + mypy + pytest
```

The suite mocks the LLM and HTTP, runs Celery eagerly, and asserts the behaviours that matter:
re-poll idempotency, chord aggregation, partial-success, and the FTS query. Type-checking is
enforced (mypy + the django-stubs plugin) — a wrong annotation fails CI.

## Status

v1: RSS + Readwise ingest, per-item condense, cross-source synthesis, daily/weekly email digest,
PWA archive with full-text search, GitHub login gated by an owner allowlist. Roadmap: newsletters,
podcasts → Whisper, push/Telegram.
