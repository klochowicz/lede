import feedparser

from briefing.sources import RawItem
from briefing.sources._http import get_capped_bytes


def fetch(config: dict[str, str]) -> list[RawItem]:
    parsed = feedparser.parse(get_capped_bytes(config["url"]))
    return [
        RawItem(
            external_id=entry.get("id") or entry.get("link", ""),
            url=entry.get("link", ""),
            title=entry.get("title", ""),
            author=entry.get("author", ""),
            raw_content=entry.get("summary", ""),
        )
        for entry in parsed.entries
    ]
