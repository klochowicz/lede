from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from briefing.models import Digest, Item, Source
from briefing.tasks import build_digest, send_digest, summarise_item
from config.celery import app as celery_app

_SAMPLES = [
    (
        "AI labs ship autonomous coding agents",
        "Several labs released agents that plan and edit code across whole repositories this week, "
        "shifting the developer-tool conversation from autocomplete toward delegation.",
    ),
    (
        "Rust keeps landing in the Linux kernel",
        "More kernel subsystems merged Rust drivers, and maintainers debated the long-term "
        "maintenance story for mixed C/Rust trees.",
    ),
    (
        "Postgres 17 sharpens vacuum and planning",
        "The release cut autovacuum overhead and improved planning for large partitioned tables, "
        "with early adopters reporting steadier tail latencies.",
    ),
]


class Command(BaseCommand):
    help = (
        "End-to-end smoke: seed sample items, summarise + synthesise cross-source themes with the "
        "configured LLM backend, and render the digest email (console backend in dev)."
    )

    def handle(self, *args: object, **options: object) -> None:
        # One-shot smoke: run the chained .delay() calls inline so no worker is required.
        celery_app.conf.task_always_eager = True
        now = timezone.now()

        source, _ = Source.objects.get_or_create(
            kind=Source.Kind.RSS, config={"url": "https://example.com/smoke"}
        )
        self.stdout.write(self.style.NOTICE("Summarising sample items with the LLM backend..."))
        for index, (title, body) in enumerate(_SAMPLES):
            item, _created = Item.objects.get_or_create(
                source=source,
                external_id=f"smoke-{index}",
                defaults={
                    "url": f"https://example.com/smoke/{index}",
                    "title": title,
                    "content_hash": f"smoke-{index}",
                    "raw_content": body,
                },
            )
            # Reset so each run re-summarises with the current backend and stays inside the window.
            Item.objects.filter(id=item.id).update(
                raw_content=body,
                summary="",
                summarised_at=None,
                summarise_failed=False,
                fetched_at=now,
            )
            summarise_item(item.id)
            item.refresh_from_db()
            self.stdout.write(f"  - {title}\n      -> {item.summary}")

        start, end = now - timedelta(minutes=1), timezone.now()
        self.stdout.write(self.style.NOTICE("Synthesising cross-source themes..."))
        digest_id = build_digest("daily", start.isoformat(), end.isoformat())

        digest = Digest.objects.get(id=digest_id)
        for theme in digest.themes.all():
            self.stdout.write(
                self.style.SUCCESS(f"  * {theme.title}  (importance {theme.importance})")
            )
            self.stdout.write(f"      {theme.narrative}")

        self.stdout.write(self.style.NOTICE("Rendering the digest email..."))
        send_digest(digest_id)
        self.stdout.write(self.style.SUCCESS("Smoke complete."))
