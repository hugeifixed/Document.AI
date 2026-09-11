import os
import subprocess
import sys

from django.conf import settings
from django.contrib import admin as django_admin
from django.test import RequestFactory

from docai.models import AuditEvent, ReviewAction


def test_production_settings_pass_django_deployment_checks():
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
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


def test_audit_records_are_immutable_in_admin(admin):
    request = RequestFactory().get("/admin/")
    request.user = admin

    for model in (AuditEvent, ReviewAction):
        model_admin = django_admin.site._registry[model]
        assert model_admin.has_view_permission(request)
        assert not model_admin.has_add_permission(request)
        assert not model_admin.has_change_permission(request)
        assert not model_admin.has_delete_permission(request)
