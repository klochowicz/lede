# Cross-Source Briefing — Django + Celery content-digest pipeline

## Context

A portfolio + personal-utility project: demonstrate **Django and Celery** convincingly to a
stranger while being genuinely useful. A long brainstorm ruled out ideas with polished
local-first incumbents (Home Assistant, Fava, OrgNote/org-roam-server, CookCLI) against a
"wrong-tool test" — for those, Django/Celery reads as reinventing a wheel.

The surviving idea gives Celery **honest, heavy work** and keeps Django central: a
**cross-source briefing pipeline**. It pulls items from content sources on a schedule, condenses
each with an LLM, then synthesises everything in a window into a small set of **cross-source
themes** ("the 3-5 things that matter this week, and why"), delivered as an email digest and a
mobile-friendly PWA archive. Wedge vs the user's Readwise: Readwise summarises *individual*
items on demand; it does not produce a scheduled *cross-source synthesis*.

### Locked decisions
- **Sources (v1):** RSS/Atom + Readwise Reader. (Newsletters, podcasts→Whisper later.)
- **LLM job:** cross-source **theme synthesis** (not per-item TL;DR).
- **Delivery:** scheduled **email digest** + **PWA/web dashboard** archive.
- **Stack:** Django first-class (portfolio), Celery the async core, Postgres, Redis.
- **LLM provider:** provider-agnostic — **Claude Max subscription (default)**, Claude API
  (fallback), DeepSeek (cheap). See LLM layer below.
- **Deploy:** Raspberry Pi (≥4GB, Postgres/repo on USB SSD) or Hetzner CX22. LLM is API/CLI-based;
  no GPU.

## Architecture

```
Celery Beat ──poll (fan-out, retried)──> Items in Postgres
                                            │
              summarise_item (per item, LLM, rate-limited, retried) ── chord ──┐
                                                                               ▼
                          build_digest (window aggregate → LLM theme synthesis → persist)
                                                                               │
                                                          ┌────────────────────┴───────────┐
                                                          ▼                                ▼
                                                    send_digest (email)        Django views / PWA (Postgres + FTS)
```

**Two halves, deliberately split (the split IS the portfolio talking point):**
- **Django** — Postgres models + read-model, dashboard views/templates, PWA manifest + minimal
  service worker (installable, not offline-first), digest archive with **Postgres full-text
  search**, `django-allauth` GitHub OAuth (login), email rendering/send, **Django admin** for
  managing sources + re-triggering runs.
- **Celery** — scheduled + chorded + retried pipeline. README documents the boundary: a one-off
  "re-summarise this item" is the kind of thing Django 6 `django.tasks` covers; the
  scheduled/chained/retried pipeline is why Celery exists.

## Data model (Postgres, Django ORM)

- `Source` — `kind` (`rss` | `readwise`), `config`, `enabled`, `last_polled_at`.
- `Item` — `source` FK, `external_id`, `url`, `title`, `author`, `raw_content`, `fetched_at`,
  **`content_hash`** (idempotency key), `summary`, `summarised_at`, `search_vector`
  (GIN-indexed). Unique on `(source, external_id)`.
- `Digest` — `period_start/end`, `kind` (daily|weekly), `status`, `created_at`.
- `Theme` — `digest` FK, `title`, `narrative`, `importance`.
- `ThemeItem` — `theme`↔`item` with per-link `rationale`.

## Celery task graph

- `poll_source(source_id)` — fetch feed (`feedparser`) or Readwise (API); upsert `Item`s
  idempotently by `content_hash`; retry transient HTTP. Beat fans out one per enabled source.
- `summarise_item(item_id)` — LLM condense via the backend layer; rate-limited + retried; skips
  already-summarised.
- `build_digest(kind)` — **chord callback**: gather window's summarised items → LLM cross-source
  theme synthesis → persist `Digest`/`Theme`/`ThemeItem` → enqueue `send_digest`. Idempotent per
  `(kind, period)`.
- `send_digest(digest_id)` — render the digest template, email it.

## LLM layer (`briefing/llm.py`) — provider-agnostic

A small `LLMBackend` protocol with two methods, `condense(text)` and `synthesise(items)`.
Everything above it (tasks, models) is backend-blind. Backend chosen via `BRIEFING_LLM_BACKEND`.

| Backend | Auth | Cost | Notes |
|---|---|---|---|
| **Claude subscription** (default) | `claude login` OAuth, via the **Claude Agent SDK** / `claude -p --output-format json` | Max included usage | Worker shells out to an authenticated CLI (same shape as a headless-render worker). Edge-of-intended-use; quota shared with interactive Claude Code use (5-hour + weekly caps); device-flow login on the box, SDK/CLI keeps tokens refreshed. |
| **Claude API** (fallback) | `ANTHROPIC_API_KEY` | pay-per-token | Anthropic SDK (reuses the `gtm/wp-audit` pattern). Models: condense `claude-haiku-4-5` ($1/$5), synthesis `claude-sonnet-4-6` ($3/$15) or `claude-opus-4-8` ($5/$25). |
| **DeepSeek** (cheap) | `DEEPSEEK_API_KEY` | ~order of magnitude cheaper | Uses the **`openai` SDK** at `base_url="https://api.deepseek.com"`, NOT the Anthropic SDK — keep that split behind the protocol. Data leaves to a third party (privacy note for the user's content). |

> The subscription path and the (deferred) headless-Whisper/Emacs ideas share one pattern:
> "worker invokes an authenticated external binary." Factor the subprocess-with-auth handling once.

## Stack & tooling (match the user's other Python projects)

- **uv** deps + **mise** task runner + **ruff** + **pyright** + **pytest-django** (mirrors
  `beancount_importer`). Django 6, Celery 5, Redis (broker+result+cache), Postgres 16,
  `django-allauth`, `feedparser`, `anthropic`, `claude-agent-sdk` (or shell out to `claude`),
  `openai` (for DeepSeek).
- **docker-compose**: `web` (gunicorn), `worker`, `beat`, `postgres`, `redis`.

## v1 scope (YAGNI)

In: RSS + Readwise ingest; per-item condense; cross-source theme synthesis; daily/weekly digest;
email + PWA archive with FTS; allauth GitHub login; Django admin for sources; the three LLM
backends behind one protocol. Out (later): newsletters, podcasts/Whisper, push/Telegram,
RAG/pgvector Q&A, offline-first SW.

## Critical files (greenfield)

- `pyproject.toml`, `.mise.toml`, `compose.yaml`, `Dockerfile`
- `config/settings.py`, `config/celery.py`, `config/urls.py`
- `briefing/models.py`, `briefing/admin.py`, `briefing/tasks.py`,
  `briefing/sources/` (`rss.py`, `readwise.py`), `briefing/llm.py` (`LLMBackend` + 3 backends),
  `briefing/views.py`, `briefing/templates/`, static `manifest.json` + `sw.js`
- `tests/`

## Verification

- `mise run dev` / `docker compose up` brings up web + worker + beat + postgres + redis.
- Add an RSS `Source` in admin → trigger `poll_source` → confirm `Item`s upserted; a **second
  poll creates no duplicates** (idempotency by `content_hash`).
- Trigger `build_digest` over a window → confirm `Digest`/`Theme`/`ThemeItem` persisted and a
  digest email renders (console backend in dev).
- Browse the PWA archive on a phone; run a full-text search.
- LLM layer: with `BRIEFING_LLM_BACKEND=claude-subscription`, a smoke task condenses one item via
  `claude -p` using the logged-in subscription. Swap to `claude-api` / `deepseek` and confirm the
  same task succeeds — proves the abstraction.
- `mise run ci` = ruff + pyright + pytest. Tests mock the LLM + HTTP, run Celery
  `task_always_eager`, assert: re-poll idempotency, chord aggregation, FTS query. (Don't mock
  tests into passing.)

## Decision trail

HA solar digest (rejected — HA does it natively); org-roam viewer (rejected — OrgNote incumbent,
narrow gap); beancount (Fava local-first incumbent); recipes (CookCLI LAN-only). Reframe: every
plain-text-git domain has a local-first viewer; the unserved gap is the hosted/push/mobile-fresh
delivery layer — domain-agnostic. Chosen: LLM cross-source briefing — Celery is the star
(scheduled + fan-out + flaky LLM I/O + chord), Django the evaluable surface, no drop-in incumbent.
