from pathlib import Path

import environ

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

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

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
