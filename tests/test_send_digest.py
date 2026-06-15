from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from briefing.models import Digest, Theme
from briefing.tasks import send_digest


def test_send_digest_renders_html_email(db):
    digest = Digest.objects.create(
        kind="daily",
        period_start=timezone.now(),
        period_end=timezone.now(),
        status=Digest.Status.READY,
    )
    Theme.objects.create(digest=digest, title="Big Theme", narrative="why", importance=5)
    send_digest(digest.id)
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert isinstance(sent, EmailMultiAlternatives)
    assert "Big Theme" in str(sent.alternatives[0][0])
    digest.refresh_from_db()
    assert digest.status == Digest.Status.SENT
