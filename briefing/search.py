from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import QuerySet

from briefing.models import Item


def search_items(query: str) -> QuerySet[Item]:
    cleaned = query.strip()
    if not cleaned:
        return Item.objects.none()
    search_query = SearchQuery(cleaned, config="english")
    return (
        Item.objects.filter(search_vector=search_query)
        .annotate(rank=SearchRank("search_vector", search_query))
        .order_by("-rank")
    )
