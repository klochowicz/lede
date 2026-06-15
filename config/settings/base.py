from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env()

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-key")
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "briefing",
]

INSTALLED_APPS += [
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.github",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

MIDDLEWARE += ["allauth.account.middleware.AccountMiddleware"]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    },
]

DATABASES = {
    "default": env.db(
        "DATABASE_URL", default="postgres://briefing:briefing@localhost:5432/briefing"
    ),
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "static/"
TIME_ZONE = "Australia/Sydney"
USE_TZ = True

# Celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
CELERY_TASK_ALWAYS_EAGER = False

# LLM backend — committed default is the reproducible, key-based one.
BRIEFING_LLM_BACKEND = env("BRIEFING_LLM_BACKEND", default="claude-api")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
DEEPSEEK_API_KEY = env("DEEPSEEK_API_KEY", default="")
READWISE_TOKEN = env("READWISE_TOKEN", default="")

# Digest windows
BRIEFING_POLL_INTERVAL_MINUTES = 30

# Digest delivery
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="briefing@localhost")
BRIEFING_DIGEST_RECIPIENT = env("BRIEFING_DIGEST_RECIPIENT", default="me@localhost")

CELERY_BEAT_SCHEDULE = {
    "poll-all-sources": {
        "task": "briefing.tasks.poll_all_sources",
        "schedule": BRIEFING_POLL_INTERVAL_MINUTES * 60,
    },
    "daily-digest": {
        "task": "briefing.tasks.kick_off_daily",
        "schedule": crontab(hour=7, minute=0),
    },
    "weekly-digest": {
        "task": "briefing.tasks.kick_off_weekly",
        "schedule": crontab(hour=8, minute=0, day_of_week="mon"),
    },
}

# django-allauth
SITE_ID = 1
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
SOCIALACCOUNT_PROVIDERS = {
    "github": {
        "APPS": [
            {
                "client_id": env("GITHUB_CLIENT_ID", default=""),
                "secret": env("GITHUB_CLIENT_SECRET", default=""),
                "key": "",
            }
        ],
        "SCOPE": ["read:user"],
    }
}
# Leave SOCIALACCOUNT_LOGIN_ON_GET at its default (False): provider login must be a
# CSRF-protected POST from the confirmation page, not a GET (avoids login CSRF).

# GitHub OAuth is the only intended way in — disable local password signup/login so a
# stranger can't POST /accounts/signup/ to mint a local account. (Restricting *which*
# GitHub users may log in is a separate owner-allowlist decision; see the plan follow-ups.)
SOCIALACCOUNT_ONLY = True
ACCOUNT_EMAIL_VERIFICATION = "none"
# Gate signup to specific GitHub usernames. Empty = open (dev); set in prod, e.g.
# BRIEFING_ALLOWED_GITHUB_LOGINS=klochowicz, to lock the app to its owner.
SOCIALACCOUNT_ADAPTER = "briefing.adapters.AllowlistSocialAccountAdapter"
BRIEFING_ALLOWED_GITHUB_LOGINS = env.list("BRIEFING_ALLOWED_GITHUB_LOGINS", default=[])

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
