from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from briefing.models import Digest, Item, Source, ThemeItem
from briefing.tasks import build_digest


def _summarised_item(source, ext, summary):
    return Item.objects.create(
        source=source,
        external_id=ext,
        url=f"https://x/{ext}",
        content_hash=ext,
        title=f"T{ext}",
        summary=summary,
        summarised_at=timezone.now(),
    )


def test_build_digest_synthesises_and_persists(db):
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    item = _summarised_item(source, "e1", "summary one")
    start, end = timezone.now() - timedelta(days=1), timezone.now() + timedelta(minutes=1)
    fake_themes = [
        {
            "title": "Theme A",
            "narrative": "n",
            "importance": 9,
            "items": [{"item_id": item.id, "rationale": "central"}],
        }
    ]
    with (
        patch("briefing.tasks.get_backend") as get_backend,
        patch("briefing.tasks.send_digest.delay") as send,
    ):
        get_backend.return_value.synthesise.return_value = fake_themes
        build_digest("daily", start.isoformat(), end.isoformat())

    digest = Digest.objects.get(kind="daily")
    assert digest.status == Digest.Status.READY
    assert digest.themes.get().title == "Theme A"
    assert ThemeItem.objects.get().item_id == item.id
    send.assert_called_once_with(digest.id)


def test_build_digest_clean_slate_on_pending_reentry(db):
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    item = _summarised_item(source, "e1", "summary one")
    start, end = timezone.now() - timedelta(days=1), timezone.now() + timedelta(minutes=1)
    fake_themes = [
        {
            "title": "Theme A",
            "narrative": "n",
            "importance": 9,
            "items": [{"item_id": item.id, "rationale": "central"}],
        }
    ]
    with (
        patch("briefing.tasks.get_backend") as get_backend,
        patch("briefing.tasks.send_digest.delay"),
    ):
        get_backend.return_value.synthesise.return_value = fake_themes
        build_digest("daily", start.isoformat(), end.isoformat())
        # Simulate a retry/re-entry that finds the digest still PENDING.
        Digest.objects.filter(kind="daily").update(status=Digest.Status.PENDING)
        build_digest("daily", start.isoformat(), end.isoformat())

    digest = Digest.objects.get(kind="daily")
    assert digest.themes.count() == 1  # not duplicated by the second run
    assert ThemeItem.objects.count() == 1


def test_build_digest_coerces_string_item_id(db):
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    item = _summarised_item(source, "e1", "summary one")
    start, end = timezone.now() - timedelta(days=1), timezone.now() + timedelta(minutes=1)
    fake_themes = [
        {
            "title": "Theme A",
            "narrative": "n",
            "importance": 9,
            "items": [{"item_id": str(item.id), "rationale": "central"}],  # model returns a string
        }
    ]
    with (
        patch("briefing.tasks.get_backend") as get_backend,
        patch("briefing.tasks.send_digest.delay"),
    ):
        get_backend.return_value.synthesise.return_value = fake_themes
        build_digest("daily", start.isoformat(), end.isoformat())

    assert ThemeItem.objects.get().item_id == item.id  # linked despite the string id


def test_build_digest_is_idempotent_per_period(db):
    start, end = timezone.now() - timedelta(days=1), timezone.now()
    with (
        patch("briefing.tasks.get_backend") as get_backend,
        patch("briefing.tasks.send_digest.delay"),
    ):
        get_backend.return_value.synthesise.return_value = []
        build_digest("daily", start.isoformat(), end.isoformat())
        build_digest("daily", start.isoformat(), end.isoformat())
    assert Digest.objects.filter(kind="daily").count() == 1
