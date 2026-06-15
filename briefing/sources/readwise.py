import json

from briefing.sources import RawItem
from briefing.sources._http import get_capped_bytes

LIST_URL = "https://readwise.io/api/v3/list/"


def fetch(config: dict[str, str]) -> list[RawItem]:
    headers = {"Authorization": f"Token {config['token']}"}
    docs: list[dict] = []
    cursor: str | None = None
    while True:
        params = {"pageCursor": cursor} if cursor else {}
        data = json.loads(get_capped_bytes(LIST_URL, headers=headers, params=params))
        docs.extend(data.get("results", []))
        cursor = data.get("nextPageCursor")
        if not cursor:
            break
    return [
        RawItem(
            external_id=str(doc["id"]),
            url=doc.get("url", ""),
            title=doc.get("title", ""),
            author=doc.get("author", ""),
            raw_content=doc.get("content") or doc.get("summary", ""),
        )
        for doc in docs
    ]
