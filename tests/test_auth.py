from django.urls import reverse


def test_login_page_offers_github(client, db):
    resp = client.get(reverse("account_login"))
    assert resp.status_code == 200
    # The page must surface the GitHub OAuth entry point — the only intended way in.
    assert "/accounts/github/login/" in resp.content.decode()


def test_socialaccount_github_provider_configured(settings):
    assert "allauth.socialaccount.providers.github" in settings.INSTALLED_APPS
    assert "github" in settings.SOCIALACCOUNT_PROVIDERS
