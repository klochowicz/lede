from unittest.mock import MagicMock, patch

from django.contrib.postgres.search import SearchQuery

from briefing.models import Item, Source
from briefing.tasks import summarise_item


def test_summarise_populates_search_vector(db):
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    item = Item.objects.create(
        source=source,
        external_id="e1",
        url="https://x/1",
        content_hash="h1",
        title="Quantum computing breakthrough",
        raw_content="body",
    )
    backend = MagicMock()
    backend.condense.return_value = "A summary about superconductors."
    with patch("briefing.tasks.get_backend", return_value=backend):
        summarise_item(item.id)

    hits = Item.objects.filter(search_vector=SearchQuery("superconductors"))
    assert item in hits
    quantum_hits = Item.objects.filter(search_vector=SearchQuery("quantum"))
    assert item in quantum_hits
