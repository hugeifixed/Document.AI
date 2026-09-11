"""Fail-closed production settings.

Local commands use ``config.settings.local`` through ``manage.py``. WSGI and
Celery default here so a deployment cannot silently inherit development hosts,
cookies, or transport security.
"""

from django.core.exceptions import ImproperlyConfigured

from . import base as base_settings
from .base import *  # noqa: F403

DEBUG = False

_DEVELOPMENT_SECRET_KEYS = {
    "",
    "change-me",
    "dev-only-insecure-key-change-me",
}
_secret_key = base_settings.SECRET_KEY
if (
    _secret_key in _DEVELOPMENT_SECRET_KEYS
    or len(_secret_key) < 50
    or len(set(_secret_key)) < 5
    or _secret_key.startswith("django-insecure-")
):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be a unique production secret of at least 50 characters."
    )

ALLOWED_HOSTS = base_settings.env.list("DJANGO_ALLOWED_HOSTS", [])
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must list explicit production host names.")

if not base_settings.env.str("DATABASE_URL", "").strip():
    raise ImproperlyConfigured("DATABASE_URL must be configured for production.")

# HTTPS is terminated either by Django's server or a trusted reverse proxy.
# Only enable the proxy header when that proxy strips client-supplied headers.
SECURE_SSL_REDIRECT = base_settings.env.bool("DJANGO_SECURE_SSL_REDIRECT", True)
if base_settings.env.bool("DJANGO_TRUST_X_FORWARDED_PROTO", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# A one-hour default limits first-deploy impact while still passing Django's
# deployment check. Increase after every required subdomain is HTTPS-ready.
SECURE_HSTS_SECONDS = base_settings.env.int("DJANGO_SECURE_HSTS_SECONDS", 3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = base_settings.env.bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False
)
SECURE_HSTS_PRELOAD = base_settings.env.bool("DJANGO_SECURE_HSTS_PRELOAD", False)

# Keep uploaded originals private on local filesystems even when the process
# umask is permissive.
FILE_UPLOAD_PERMISSIONS = 0o640
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750

# Cross-origin access is opt-in in production. Same-origin deployments need
# neither list.
CORS_ALLOWED_ORIGINS = base_settings.env.list("DOCAI_CORS_ORIGINS", [])
CSRF_TRUSTED_ORIGINS = base_settings.env.list("DOCAI_CSRF_TRUSTED", [])

# Basic authentication repeatedly sends the password. Session auth is the
# production default; service owners can explicitly enable Basic over HTTPS.
_authentication_classes = ["docai.api.authentication.ChallengeSessionAuthentication"]
if base_settings.env.bool("DOCAI_ENABLE_BASIC_AUTH", False):
    _authentication_classes.append("rest_framework.authentication.BasicAuthentication")
REST_FRAMEWORK = {
    **base_settings.REST_FRAMEWORK,
    "DEFAULT_AUTHENTICATION_CLASSES": _authentication_classes,
}

# API documentation describes internal endpoints and requires an existing
# authenticated session in production.
SPECTACULAR_SETTINGS = {
    **base_settings.SPECTACULAR_SETTINGS,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
}

DOCAI_LOG_JSON = base_settings.env.bool("DOCAI_LOG_JSON", True)
