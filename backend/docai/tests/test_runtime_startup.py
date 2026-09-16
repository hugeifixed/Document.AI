from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from loguru import logger

from docai.logging.setup import _console_context
from docai.logging.startup import log_startup


def test_startup_summary_is_useful_without_exposing_connections(settings, monkeypatch):
    monkeypatch.setenv(
        "HTTPS_PROXY", "http://private-user:private-password@private-proxy.invalid:90"
    )
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/private/path/institution.pem")
    settings.DOCAI_ENVIRONMENT = "rnd"
    settings.DOCAI = {**settings.DOCAI, "TASK_RUNNER": "celery"}
    settings.CELERY_BROKER_URL = (
        "redis://private-user:private-password@private-broker.invalid:6379/0"
    )
    settings.CELERY_WORKER_POOL = "solo"
    settings.CELERY_WORKER_CONCURRENCY = 10
    records = []
    sink = logger.add(lambda message: records.append(message.record))
    try:
        log_startup("web")
    finally:
        logger.remove(sink)
    assert len(records) == 3
    first, runtime, network = [record["extra"] for record in records]
    assert first["environment"] == "rnd"
    assert first["pid"] == os.getpid()
    assert first["python"] and first["django"]
    assert "environment=rnd" in _console_context(records[0])
    assert runtime["database"] == "sqlite3"
    assert runtime["configured_pool"] == "solo"
    assert runtime["configured_slots"] == 1
    assert runtime["broker"] == "redis"
    assert network["proxy_env_configured"] is True
    assert network["identity_di_ca"] == "custom"
    assert network["verify_ssl"] is True
    assert "private-" not in json.dumps([record["extra"] for record in records], default=str)
    assert "/private/path" not in json.dumps(network)


@pytest.mark.parametrize("command", ["django", "pytest"])
def test_test_commands_override_inherited_deployment_settings(tmp_path, settings, command):
    module = tmp_path / "test_isolated_profile.py"
    module.write_text("""from django.conf import settings
from unittest import TestCase

class TestProfile(TestCase):
    def test_sqlite_is_used(self):
        assert settings.SETTINGS_MODULE == "config.settings.test"
        assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
        assert settings.DATABASES["default"]["NAME"] == ":memory:"
        assert settings.AZURE_VERIFY_SSL is True
""")
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "DATABASE_URL": "oracle://private-user:private-password@private-db.invalid:1521/service",
        "DOCAI_TASK_RUNNER": "sync",
        "AZURE_VERIFY_SSL": "false",
        "PYTHONPATH": os.pathsep.join((str(tmp_path), str(settings.BASE_DIR))),
    }
    args = (
        ["manage.py", "test", "test_isolated_profile", "--noinput"]
        if command == "django"
        else ["-m", "pytest", "-c", "pyproject.toml", str(module)]
    )
    result = subprocess.run(  # noqa: S603 -- fixed offline test command; no production database calls
        [sys.executable, *args],
        cwd=settings.BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DocAI runtime initialized" not in result.stdout + result.stderr


def test_deployed_settings_reject_tls_bypass(settings):
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "AZURE_VERIFY_SSL": "false",
    }
    result = subprocess.run(  # noqa: S603 -- fixed configuration-only subprocess
        [
            sys.executable,
            "-c",
            "from django.conf import settings; print(settings.AZURE_VERIFY_SSL)",
        ],
        cwd=settings.BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode != 0
    assert "only supported for local debugging" in result.stderr
    assert "REQUESTS_CA_BUNDLE" in result.stderr


def test_wsgi_initialization_logs_once_and_celery_ready_reports_its_role(settings):
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "DOCAI_LOG_JSON": "true",
        "DOCAI_LOG_LEVEL": "INFO",
    }
    script = """
import config.wsgi
import config.wsgi
from loguru import logger
logger.complete()
"""
    result = subprocess.run(  # noqa: S603 -- fixed offline WSGI initialization, no socket binding
        [sys.executable, "-c", script],
        cwd=settings.BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in result.stdout.splitlines()]
    startup = [record for record in records if record.get("event") == "runtime_startup"]
    assert len(startup) == 1
    assert startup[0]["role"] == "web"
    assert startup[0]["environment"] == "test"

    signals = pytest.importorskip("celery.signals")
    captured = []
    sink = logger.add(lambda message: captured.append(message.record["extra"]))
    try:
        signals.worker_ready.send(sender=object())
    finally:
        logger.remove(sink)
    assert any(record.get("role") == "celery_worker" for record in captured)
