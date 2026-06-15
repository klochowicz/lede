from unittest.mock import patch

from briefing.models import Source
from briefing.tasks import poll_all_sources


def test_poll_all_sources_fans_out_to_enabled_only(db):
    enabled = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://y/feed"}, enabled=False)
    with patch("briefing.tasks.poll_source.delay") as delay:
        poll_all_sources()
    delay.assert_called_once_with(enabled.id)
