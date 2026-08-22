"""Django settings for the concurrent wallet service."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from psycopg import IsolationLevel

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env", override=False)


def env(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value or ""


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = env(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        return default


DEV_SECRET_KEY = "insecure-development-key-replace-me-before-any-real-deployment"

SECRET_KEY = env("DJANGO_SECRET_KEY", DEV_SECRET_KEY)
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]

# Deployment and cookie-based auth are out of scope: there are no HTML pages,
# no sessions and no CSRF surface, so these deployment checks do not apply here.
SILENCED_SYSTEM_CHECKS = [
    "security.W002",  # X-Frame-Options: JSON API, never framed
    "security.W003",  # CSRF: no cookie authentication at all
    "security.W004",  # HSTS: terminated by the platform, not by Django
    "security.W008",  # SSL redirect: same
]

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "wallets",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

# PostgreSQL only, by design: the correctness of this service depends on
# SELECT ... FOR UPDATE row locking, which SQLite does not provide.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "wallet"),
        "USER": env("POSTGRES_USER", "wallet"),
        "PASSWORD": env("POSTGRES_PASSWORD", "wallet"),
        "HOST": env("POSTGRES_HOST", "127.0.0.1"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": env_int("POSTGRES_CONN_MAX_AGE", 0),
        "OPTIONS": {
            "connect_timeout": env_int("POSTGRES_CONNECT_TIMEOUT", 10),
            # READ COMMITTED + explicit row locks: no serialization failures to
            # retry, and the lock window stays as small as the debit itself.
            "isolation_level": IsolationLevel.READ_COMMITTED,
        },
        "TEST": {"NAME": env("POSTGRES_TEST_DB", "test_wallet")},
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Business invariant: money is exact. Never float.
WALLET_DECIMAL_PLACES = 2
WALLET_MAX_DIGITS = 18

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"

REST_FRAMEWORK = {
    # Authentication is explicitly out of scope for this exercise, so the
    # request never needs a user object at all.
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
    "DEFAULT_PAGINATION_CLASS": "wallets.pagination.DefaultPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "wallets.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Concurrent Wallet API",
    "DESCRIPTION": "Idempotent, race-safe wallet debits backed by PostgreSQL row locks.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
}
