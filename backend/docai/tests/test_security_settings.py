import os
import subprocess
import sys
from typing import Any, cast

from django.conf import settings
from django.contrib import admin as django_admin
from django.test import RequestFactory

from docai.models import AuditEvent, ReviewAction


def test_request_profiler_is_disabled_by_default():
    assert settings.SILKY_ENABLED is False
    assert "silk" not in settings.INSTALLED_APPS
    assert "silk.middleware.SilkyMiddleware" not in settings.MIDDLEWARE
    assert settings.SILKY_MAX_REQUEST_BODY_SIZE == 0
    assert settings.SILKY_MAX_RESPONSE_BODY_SIZE == 0


def test_session_authentication_has_a_stable_unauthenticated_contract():
    classes = cast(dict[str, Any], settings.REST_FRAMEWORK)["DEFAULT_AUTHENTICATION_CLASSES"]
    assert classes[0] == "docai.api.authentication.ChallengeSessionAuthentication"


def test_request_profiler_can_be_enabled_entirely_from_environment():
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings.test",
            "DJANGO_SILKY_ENABLED": "true",
        }
    )
    script = """
import django
django.setup()
from django.conf import settings
from django.urls import resolve, reverse
assert settings.SILKY_ENABLED is True
assert 'silk' in settings.INSTALLED_APPS
assert 'silk.middleware.SilkyMiddleware' in settings.MIDDLEWARE
assert settings.SILKY_AUTHENTICATION is True
assert settings.SILKY_AUTHORISATION is True
assert settings.SILKY_PERMISSIONS(type('User', (), {'is_superuser': True})()) is True
assert settings.SILKY_PERMISSIONS(type('User', (), {'is_superuser': False})()) is False
assert settings.LOGIN_URL == '/admin/login/'
assert reverse('silk:summary') == '/admin/profiler/'
assert resolve('/admin/profiler/').url_name == 'summary'
print('silky enabled')
"""
    completed = subprocess.run(  # noqa: S603 -- interpreter and inline script are fixed test inputs
        [sys.executable, "-c", script],
        cwd=settings.BASE_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "silky enabled"


def test_production_settings_pass_django_deployment_checks():
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "DOCAI_ENVIRONMENT": "qa",
            "DJANGO_SECRET_KEY": "deployment-check-only!7vQ9$kL2#sR8@zM4%pT6&xW3*cN5^hJ1",
            "DJANGO_ALLOWED_HOSTS": "docai.example.test",
            "DATABASE_URL": "sqlite:///:memory:",
            "DJANGO_DEBUG": "true",
            "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS": "true",
            "DJANGO_SECURE_HSTS_PRELOAD": "true",
        }
    )
    completed = subprocess.run(
        [sys.executable, "manage.py", "check", "--deploy"],
        cwd=settings.BASE_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "System check identified no issues" in output


def test_production_settings_reject_unknown_environment():
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "DOCAI_ENVIRONMENT": "development",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=settings.BASE_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
    assert "DOCAI_ENVIRONMENT must be one of rnd, uat, qa, or prod" in completed.stderr


def test_audit_records_are_immutable_in_admin(admin):
    request = RequestFactory().get("/admin/")
    request.user = admin

    for model in (AuditEvent, ReviewAction):
        model_admin = django_admin.site._registry[model]
        assert model_admin.has_view_permission(request)
        assert not model_admin.has_add_permission(request)
        assert not model_admin.has_change_permission(request)
        assert not model_admin.has_delete_permission(request)
