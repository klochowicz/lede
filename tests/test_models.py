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
    item = Item.objects.create(
        source=source, external_id="e2", url="https://x/2", content_hash="h3"
    )
    assert item.summary == ""
    assert item.summarised_at is None
