from unittest.mock import MagicMock, patch

from django.utils import timezone

from briefing.models import Item, Source
from briefing.tasks import summarise_item


def _item(db, summary=""):
    # Mirror the production invariant: a summary and its timestamp are set together.
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    return Item.objects.create(
        source=source,
        external_id="e1",
        url="https://x/1",
        content_hash="h1",
        raw_content="body",
        summary=summary,
        summarised_at=timezone.now() if summary else None,
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
    # Drive Celery's real request: on the final attempt the task must mark the item failed and
    # return None (not raise), so the chord callback still runs.
    summarise_item.push_request(retries=summarise_item.max_retries)
    try:
        with patch("briefing.tasks.get_backend", return_value=backend):
            result = summarise_item.run(item.id)
    finally:
        summarise_item.pop_request()
    item.refresh_from_db()
    assert item.summarise_failed is True
    assert result is None
