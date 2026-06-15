from django.contrib.postgres.search import SearchVector
from django.utils import timezone

from briefing.models import Item, Source
from briefing.search import search_items


def _item(source: Source, ext: str, title: str, summary: str) -> Item:
    item = Item.objects.create(
        source=source,
        external_id=ext,
        url=f"https://x/{ext}",
        content_hash=ext,
        title=title,
        summary=summary,
        summarised_at=timezone.now(),
    )
    Item.objects.filter(id=item.id).update(
        search_vector=SearchVector("title", "summary", config="english")
    )
    return item


def test_search_ranks_and_filters(db: None) -> None:
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    relevant = _item(source, "e1", "Rust async runtime", "tokio and futures explained")
    _item(source, "e2", "Baking sourdough", "hydration and crumb")

    results = list(search_items("tokio"))
    assert relevant in results
    assert len(results) == 1


def test_search_blank_query_returns_empty(db: None) -> None:
    assert list(search_items("   ")) == []
