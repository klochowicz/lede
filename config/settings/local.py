from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Local-dev default: free-at-margin via the developer's logged-in Claude subscription.
BRIEFING_LLM_BACKEND = env("BRIEFING_LLM_BACKEND", default="claude-subscription")  # noqa: F405

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "briefing@localhost"
