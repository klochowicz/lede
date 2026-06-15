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
