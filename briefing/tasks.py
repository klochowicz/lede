import hashlib
from datetime import datetime, timedelta

from celery import Task, chord, shared_task
from django.conf import settings
from django.contrib.postgres.search import SearchVector
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from briefing.llm import SynthesisItem, get_backend
from briefing.models import Digest, Item, Source, Theme, ThemeItem
from briefing.sources import fetch_source


@shared_task
def ping() -> str:
    return "pong"


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
                "url": raw.url,
                "title": raw.title,
                "author": raw.author,
                "raw_content": raw.raw_content,
                "content_hash": digest,
            },
        )
        if created:
            touched_ids.append(item.id)
        elif item.content_hash != digest:
            item.url, item.title, item.author = raw.url, raw.title, raw.author
            item.raw_content, item.content_hash = raw.raw_content, digest
            item.summary, item.summarised_at, item.summarise_failed = "", None, False
            item.save(
                update_fields=[
                    "url",
                    "title",
                    "author",
                    "raw_content",
                    "content_hash",
                    "summary",
                    "summarised_at",
                    "summarise_failed",
                ]
            )
            touched_ids.append(item.id)
    source.last_polled_at = timezone.now()
    source.save(update_fields=["last_polled_at"])
    return touched_ids


@shared_task(bind=True, max_retries=3, retry_backoff=True)
def summarise_item(self: Task, item_id: int) -> int | None:
    item = Item.objects.get(id=item_id)
    if item.summarised_at is not None:
        return item.id
    try:
        summary = get_backend().condense(item.raw_content)
    except Exception as exc:  # noqa: BLE001 — partial-success policy: a dead item must not abort the chord
        if self.request.retries >= self.max_retries:
            Item.objects.filter(id=item_id).update(summarise_failed=True)
            return None
        raise self.retry(exc=exc) from exc
    item.summary, item.summarised_at, item.summarise_failed = summary, timezone.now(), False
    item.save(update_fields=["summary", "summarised_at", "summarise_failed"])
    Item.objects.filter(id=item_id).update(
        search_vector=SearchVector("title", "summary", config="english")
    )
    return item.id


@shared_task
def kick_off_digest(kind: str, period_start: str, period_end: str) -> None:
    start, end = datetime.fromisoformat(period_start), datetime.fromisoformat(period_end)
    pending = list(
        Item.objects.filter(
            fetched_at__gte=start, fetched_at__lt=end, summarised_at__isnull=True
        ).values_list("id", flat=True)
    )
    callback = build_digest.si(kind, period_start, period_end)
    if not pending:
        callback.delay()
        return
    chord((summarise_item.s(item_id) for item_id in pending), callback).delay()


@shared_task
def build_digest(kind: str, period_start: str, period_end: str) -> int:
    start, end = datetime.fromisoformat(period_start), datetime.fromisoformat(period_end)
    with transaction.atomic():
        digest, created = Digest.objects.select_for_update().get_or_create(
            kind=kind, period_start=start, period_end=end
        )
        if not created and digest.status != Digest.Status.PENDING:
            return digest.id
        # Clean slate so a retry / re-entry while PENDING rebuilds rather than duplicating themes.
        digest.themes.all().delete()

    items = list(
        Item.objects.filter(
            fetched_at__gte=start, fetched_at__lt=end, summarised_at__isnull=False
        ).exclude(summary="")
    )
    payload: list[SynthesisItem] = [
        {"item_id": i.id, "title": i.title, "summary": i.summary} for i in items
    ]
    by_id = {i.id: i for i in items}

    for theme_data in get_backend().synthesise(payload):
        theme = Theme.objects.create(
            digest=digest,
            title=theme_data["title"],
            narrative=theme_data["narrative"],
            importance=theme_data.get("importance", 0),
        )
        for link in theme_data.get("items", []):
            item_id = _as_item_id(link.get("item_id"))
            if item_id is None:
                continue
            item = by_id.get(item_id)
            if item is not None:
                ThemeItem.objects.create(
                    theme=theme, item=item, rationale=link.get("rationale", "")
                )

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
        to=[settings.BRIEFING_DIGEST_RECIPIENT],
    )
    message.attach_alternative(html, "text/html")
    message.send()
    digest.status = Digest.Status.SENT
    digest.save(update_fields=["status"])


@shared_task
def poll_all_sources() -> None:
    for source_id in Source.objects.filter(enabled=True).values_list("id", flat=True):
        poll_source.delay(source_id)


@shared_task
def kick_off_daily() -> None:
    end = timezone.now()
    kick_off_digest("daily", (end - timedelta(days=1)).isoformat(), end.isoformat())


def _as_item_id(value: object) -> int | None:
    # The model may echo item_id as a string despite the prompt asking for int; coerce defensively.
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
