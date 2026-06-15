from dataclasses import dataclass

from briefing.models import Source


@dataclass(frozen=True)
class RawItem:
    external_id: str
    url: str
    title: str
    author: str
    raw_content: str


def fetch_source(source: Source) -> list[RawItem]:
    from briefing.sources import readwise, rss

    if source.kind == Source.Kind.RSS:
        return rss.fetch(source.config)
    if source.kind == Source.Kind.READWISE:
        return readwise.fetch(source.config)
    raise ValueError(f"Unknown source kind: {source.kind!r}")
