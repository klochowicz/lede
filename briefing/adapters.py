from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialLogin
from django.conf import settings
from django.http import HttpRequest


class AllowlistSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Restrict social signup to an allowlist of GitHub usernames.

    An empty ``BRIEFING_ALLOWED_GITHUB_LOGINS`` means open (dev convenience); set it in
    production to lock the app to its owner(s). Blocking signup is what stops a stranger's
    GitHub account from being created and then logged in.
    """

    def is_open_for_signup(self, request: HttpRequest, sociallogin: SocialLogin) -> bool:
        return _is_allowed(sociallogin)


def _is_allowed(sociallogin: SocialLogin) -> bool:
    allowed = settings.BRIEFING_ALLOWED_GITHUB_LOGINS
    if not allowed:
        return True
    login = (sociallogin.account.extra_data or {}).get("login", "")
    return str(login).lower() in {name.lower() for name in allowed}
