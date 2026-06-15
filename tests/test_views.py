from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from briefing.models import Digest, Theme


def _login(client):
    User.objects.create_user("u", password="pw")
    client.login(username="u", password="pw")


def test_dashboard_shows_latest_digest(client, db):
    _login(client)
    digest = Digest.objects.create(
        kind="daily",
        period_start=timezone.now(),
        period_end=timezone.now(),
        status=Digest.Status.SENT,
    )
    Theme.objects.create(digest=digest, title="Headline Theme", narrative="n", importance=9)
    resp = client.get(reverse("briefing:dashboard"))
    assert resp.status_code == 200
    assert b"Headline Theme" in resp.content


def test_views_require_login(client, db):
    resp = client.get(reverse("briefing:dashboard"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.headers["Location"]


def test_search_view_renders_hits(client, db):
    from django.contrib.postgres.search import SearchVector

    from briefing.models import Item, Source

    _login(client)
    source = Source.objects.create(kind=Source.Kind.RSS, config={"url": "https://x/feed"})
    item = Item.objects.create(
        source=source,
        external_id="e1",
        url="https://x/1",
        content_hash="h1",
        title="Kubernetes operators",
        summary="reconcile loops",
        summarised_at=timezone.now(),
    )
    Item.objects.filter(id=item.id).update(
        search_vector=SearchVector("title", "summary", config="english")
    )
    resp = client.get(reverse("briefing:search"), {"q": "kubernetes"})
    assert resp.status_code == 200
    assert b"Kubernetes operators" in resp.content
