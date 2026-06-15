from unittest.mock import MagicMock

from briefing.adapters import _is_allowed


def _sociallogin(login):
    sl = MagicMock()
    sl.account.extra_data = {"login": login}
    return sl


def test_empty_allowlist_is_open(settings):
    settings.BRIEFING_ALLOWED_GITHUB_LOGINS = []
    assert _is_allowed(_sociallogin("anyone")) is True


def test_allowlist_permits_listed_login_case_insensitively(settings):
    settings.BRIEFING_ALLOWED_GITHUB_LOGINS = ["klochowicz"]
    assert _is_allowed(_sociallogin("Klochowicz")) is True


def test_allowlist_rejects_unlisted_login(settings):
    settings.BRIEFING_ALLOWED_GITHUB_LOGINS = ["klochowicz"]
    assert _is_allowed(_sociallogin("stranger")) is False
