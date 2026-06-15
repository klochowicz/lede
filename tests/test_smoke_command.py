from unittest.mock import MagicMock, patch

from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.core.management import call_command

from briefing.models import Digest


def test_smoke_digest_command_end_to_end(db):
    backend = MagicMock()
    backend.condense.return_value = "a concise summary"
    backend.synthesise.return_value = [
        {"title": "The Theme", "narrative": "why it matters", "importance": 8, "items": []}
    ]
    with patch("briefing.tasks.get_backend", return_value=backend):
        call_command("smoke_digest")

    digest = Digest.objects.filter(kind="daily").latest("created_at")
    assert digest.themes.get().title == "The Theme"
    sent = mail.outbox[-1]
    assert isinstance(sent, EmailMultiAlternatives)
    assert "The Theme" in str(sent.alternatives[0][0])
