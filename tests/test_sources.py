from pathlib import Path

import pytest
import responses

from briefing.sources import RawItem
from briefing.sources._http import MAX_RESPONSE_BYTES
from briefing.sources.readwise import fetch as fetch_readwise
from briefing.sources.rss import fetch as fetch_rss

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


@responses.activate
def test_rss_fetch_normalises_entries():
    responses.add(responses.GET, "https://demo/feed", body=FIXTURE.read_text(), status=200)
    items = fetch_rss({"url": "https://demo/feed"})
    assert len(items) == 2
    assert items[0] == RawItem(
        external_id="post-1",
        url="https://demo/1",
        title="First",
        author="alice",
        raw_content="Body one",
    )


@responses.activate
def test_readwise_fetch_normalises_documents():
    responses.add(
        responses.GET,
        "https://readwise.io/api/v3/list/",
        json={
            "results": [
                {
                    "id": "d1",
                    "url": "https://r/1",
                    "title": "Doc",
                    "author": "carol",
                    "summary": "sum",
                    "content": "full",
                }
            ],
            "nextPageCursor": None,
        },
        status=200,
    )
    items = fetch_readwise({"token": "rw-test"})
    assert items[0].external_id == "d1"
    assert items[0].raw_content == "full"


@responses.activate
def test_readwise_follows_pagination():
    responses.add(
        responses.GET,
        "https://readwise.io/api/v3/list/",
        json={"results": [{"id": "d1", "content": "one"}], "nextPageCursor": "cursor-2"},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://readwise.io/api/v3/list/",
        json={"results": [{"id": "d2", "content": "two"}], "nextPageCursor": None},
        status=200,
    )
    items = fetch_readwise({"token": "rw-test"})
    assert [item.external_id for item in items] == ["d1", "d2"]


@responses.activate
def test_rss_fetch_rejects_oversized_response():
    responses.add(
        responses.GET, "https://demo/feed", body="x" * (MAX_RESPONSE_BYTES + 1), status=200
    )
    with pytest.raises(ValueError, match="exceeds"):
        fetch_rss({"url": "https://demo/feed"})
