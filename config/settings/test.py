from .base import *  # noqa: F403

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = (
    False  # mirror prod: a failed chord-header task must not abort the chord
)
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
BRIEFING_LLM_BACKEND = "claude-api"  # tests inject a fake backend; this is just a valid default
