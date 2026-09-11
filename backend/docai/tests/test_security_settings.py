import os
import subprocess
import sys
from typing import Any, cast

from django.conf import settings
from django.contrib import admin as django_admin
from django.test import RequestFactory

from docai.models import AuditEvent, ReviewAction


def test_request_profiler_can_be_disabled_entirely_from_environment():
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings.test",
            "DJANGO_SILKY_ENABLED": "false",
        }
    )
    script = """
import django
django.setup()
from django.conf import settings
assert settings.SILKY_ENABLED is False
assert 'silk' not in settings.INSTALLED_APPS
assert 'silk.middleware.SilkyMiddleware' not in settings.MIDDLEWARE
assert settings.SILKY_MAX_REQUEST_BODY_SIZE == 0
assert settings.SILKY_MAX_RESPONSE_BODY_SIZE == 0
print('silky disabled')
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
    assert completed.stdout.strip() == "silky disabled"


def test_session_authentication_has_a_stable_unauthenticated_contract():
    classes = cast(dict[str, Any], settings.REST_FRAMEWORK)["DEFAULT_AUTHENTICATION_CLASSES"]
    assert classes[0] == "docai.api.authentication.ChallengeSessionAuthentication"


def test_local_sqlite_waits_for_write_reservations():
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings.local",
            "DATABASE_URL": "sqlite:///:memory:",
            "DJANGO_SILKY_ENABLED": "false",
        }
    )
    script = """
import django
django.setup()
from django.conf import settings
options = settings.DATABASES['default']['OPTIONS']
assert options['timeout'] == 30
assert options['transaction_mode'] == 'IMMEDIATE'
print('sqlite contention settings enabled')
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
    assert completed.stdout.strip() == "sqlite contention settings enabled"


def test_local_admin_site_url_defaults_to_vite_and_allows_override():
    cases = (
        ("", "http://localhost:5173/"),
        ("https://docai-qa.example.test/workspace/", "https://docai-qa.example.test/workspace/"),
    )

    for configured_url, expected_url in cases:
        environment = os.environ.copy()
        environment.update(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings.local",
                "DATABASE_URL": "sqlite:///:memory:",
                "DJANGO_SILKY_ENABLED": "false",
                "DOCAI_FRONTEND_URL": configured_url,
                "EXPECTED_FRONTEND_URL": expected_url,
            }
        )
        script = """
import os
import django
django.setup()
from django.conf import settings
assert settings.DOCAI_FRONTEND_URL == os.environ['EXPECTED_FRONTEND_URL']
assert settings.UNFOLD['SITE_URL'] == os.environ['EXPECTED_FRONTEND_URL']
print('admin site URL configured')
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
        assert completed.stdout.strip() == "admin site URL configured"


def test_admin_view_site_link_uses_configured_frontend_url(client, admin, settings):
    frontend_url = "https://docai-uat.example.test/workspace/"
    settings.UNFOLD = {**settings.UNFOLD, "SITE_URL": frontend_url}
    client.force_login(admin)

    response = client.get("/admin/")

    assert response.status_code == 200
    assert response.context["site_url"] == frontend_url
    assert f'href="{frontend_url}"' in response.content.decode()


def test_oracle_does_not_receive_sqlite_contention_settings():
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": "oracle://docai_app:replace-me@db.example.test:1521/service",
            "DJANGO_SILKY_ENABLED": "false",
        }
    )
    script = """
from config.settings import local
database = local.DATABASES['default']
assert database['ENGINE'] == 'django.db.backends.oracle'
assert 'transaction_mode' not in database.get('OPTIONS', {})
assert 'timeout' not in database.get('OPTIONS', {})
assert local.CELERY_WORKER_CONCURRENCY == local.DOCAI['MAX_WORKERS']
print('server database settings remain backend-neutral')
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
    assert completed.stdout.strip() == "server database settings remain backend-neutral"


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
from django.template.loader import render_to_string
from django.urls import resolve, reverse
assert settings.SILKY_ENABLED is True
assert 'silk' in settings.INSTALLED_APPS
assert 'silk.middleware.SilkyMiddleware' in settings.MIDDLEWARE
assert settings.SILKY_AUTHENTICATION is True
assert settings.SILKY_AUTHORISATION is True
assert settings.SILKY_PERMISSIONS(type('User', (), {'is_superuser': True})()) is True
assert settings.SILKY_PERMISSIONS(type('User', (), {'is_superuser': False})()) is False
assert settings.SILKY_INTERCEPT_FUNC.__name__ == 'should_profile_silk_request'
assert settings.LOGIN_URL == '/admin/login/'
assert reverse('silk:summary') == '/admin/profiler/'
assert resolve('/admin/profiler/').url_name == 'summary'
platform = {
    'app_url': '/admin/docai/',
    'groups': [{'key': 'workspace', 'title': 'Workspace', 'description': '', 'items': []}],
}
request = type('Request', (), {'user': type('User', (), {'is_superuser': True})()})()
admin_home = render_to_string(
    'docai/admin/platform_groups.html',
    {'platform': platform, 'request': request},
)
assert 'href="/admin/profiler/"' in admin_home
assert 'Request profiler' in admin_home
request.user.is_superuser = False
restricted_admin_home = render_to_string(
    'docai/admin/platform_groups.html',
    {'platform': platform, 'request': request},
)
assert 'Request profiler' not in restricted_admin_home
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
