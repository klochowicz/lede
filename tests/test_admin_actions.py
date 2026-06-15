from unittest.mock import patch

from django.contrib.admin.sites import AdminSite

from briefing.admin import SourceAdmin
from briefing.models import Source


def test_poll_now_action_enqueues_poll(db):
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    admin = SourceAdmin(Source, AdminSite())
    with patch("briefing.admin.poll_source.delay") as delay:
        admin.poll_now(request=None, queryset=Source.objects.all())
    delay.assert_called_once_with(source.id)
