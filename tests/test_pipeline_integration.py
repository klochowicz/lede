from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import responses
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from briefing.models import Digest, Item, Source
from briefing.tasks import kick_off_digest, poll_source

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


@responses.activate
def test_full_pipeline_poll_summarise_digest_email(db):
    responses.add(responses.GET, "https://demo/feed", body=FIXTURE.read_text(), status=200)
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://demo/feed"})

    poll_source(source.id)
    poll_source(source.id)  # second poll: no duplicates
    assert Item.objects.filter(source=source).count() == 2

    backend = MagicMock()
    backend.condense.return_value = "a summary"
    backend.synthesise.return_value = [
        {"title": "The Theme", "narrative": "why it matters", "importance": 8, "items": []}
    ]
    start, end = timezone.now() - timedelta(hours=1), timezone.now() + timedelta(hours=1)
    with patch("briefing.tasks.get_backend", return_value=backend):
        kick_off_digest("daily", start.isoformat(), end.isoformat())

    digest = Digest.objects.get(kind="daily")
    assert digest.status == Digest.Status.SENT
    assert digest.themes.get().title == "The Theme"
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert isinstance(sent, EmailMultiAlternatives)
    assert "The Theme" in str(sent.alternatives[0][0])
