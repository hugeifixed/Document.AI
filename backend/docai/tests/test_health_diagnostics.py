from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from health_check import DNS
from health_check.exceptions import ServiceUnavailable

from docai.checks import health_configuration_checks
from docai.health import DiskCapacity, EndpointDNS, RedisPing, extended_checks


@pytest.fixture
def diagnostics(settings, tmp_path):
    settings.DOCAI_HEALTH_EXTENDED_ENABLED = True
    settings.DOCAI_HEALTH_DISK_PATH = str(tmp_path)
    settings.DOCAI_HEALTH_DISK_MAX_USED_PERCENT = 100
    settings.DOCAI_HEALTH_DISK_REQUIRE_MOUNT = False
    settings.DOCAI_HEALTH_DNS_ENDPOINTS = {}
    settings.DOCAI = {
        **settings.DOCAI,
        "LAYOUT_ADAPTER": "pypdf",
        "LLM_ADAPTER": "mock",
        "TASK_RUNNER": "thread",
    }
    return settings


def test_diagnostics_follow_selected_adapters_and_can_be_disabled(diagnostics):
    diagnostics.DOCAI = {
        **diagnostics.DOCAI,
        "LAYOUT_ADAPTER": "azure_di",
        "AZURE_DI_ENDPOINT": "https://private-di.example/path?secret=hidden",
        "AZURE_OPENAI_ENDPOINT": "https://unused.example",
    }
    diagnostics.DOCAI_HEALTH_DNS_ENDPOINTS = {"identity": "https://identity.example/tenant"}
    checks = {check.key: check for check in extended_checks()}
    assert set(checks) == {"disk", "dns_azure_di", "dns_external_identity"}
    assert checks["dns_azure_di"].probe.hostname == "private-di.example"
    assert "hidden" not in repr(checks)
    assert "private-di.example" not in str(checks["dns_azure_di"].labels)
    diagnostics.DOCAI_HEALTH_EXTENDED_ENABLED = False
    assert list(extended_checks()) == []


def test_redis_detects_cache_replicas_and_active_broker(diagnostics):
    diagnostics.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": ["rediss://user:secret@primary.example/0", "rediss://replica.example/0"],
        }
    }
    diagnostics.CELERY_BROKER_URL = "redis://broker.example/1"
    assert {check.key for check in extended_checks()} == {"disk", "redis_cache_1", "redis_cache_2"}
    diagnostics.DOCAI = {**diagnostics.DOCAI, "TASK_RUNNER": "celery"}
    checks = {check.key: check for check in extended_checks()}
    assert "redis_broker" in checks
    assert "secret" not in repr(checks)


@pytest.mark.django_db
@pytest.mark.parametrize("format_name", ["json", "text", "html", "openmetrics", "atom", "rss"])
def test_external_failure_is_sanitized_and_does_not_fail_readiness(
    client, diagnostics, monkeypatch, format_name
):
    diagnostics.DOCAI_HEALTH_DNS_ENDPOINTS = {"identity": "private.example"}
    probe = AsyncMock(side_effect=ServiceUnavailable("private.example rejected secret-value"))
    monkeypatch.setattr(DNS, "run", probe)
    response = client.get(f"/health/?format={format_name}", HTTP_HOST="localhost")
    assert response.status_code == (200 if format_name in {"openmetrics", "atom", "rss"} else 503)
    assert "private.example" not in response.content.decode()
    assert "secret-value" not in response.content.decode()
    assert str(diagnostics.DOCAI_HEALTH_DISK_PATH) not in response.content.decode()
    if format_name == "json":
        assert response.json()["checks"]["dns_external_identity"]["status"] == "unavailable"
    probe.reset_mock()
    ready = client.get("/health/ready/", HTTP_HOST="localhost")
    assert ready.status_code == 200
    assert set(ready.json()["checks"]) == {"database", "cache", "storage"}
    assert client.get("/health/live/", HTTP_HOST="localhost").status_code == 200
    probe.assert_not_called()


def test_dns_uses_configured_resolver_timeout_and_handles_missing_endpoint(monkeypatch):
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=["127.0.0.1"]), lifetime=None)
    monkeypatch.setattr("dns.asyncresolver.Resolver", lambda: resolver)
    assert asyncio.run(EndpointDNS(hostname="private.example").get_result()).error is None
    resolver.resolve.assert_awaited_once_with("private.example", "A")
    assert resolver.lifetime == 5
    assert asyncio.run(EndpointDNS(hostname="").get_result()).error is not None


@pytest.mark.parametrize("failure", [None, "authentication", "timeout"])
def test_redis_ping_closes_connections_and_bounds_failure(monkeypatch, failure):
    redis = pytest.importorskip("redis.asyncio")
    exceptions = pytest.importorskip("redis.exceptions")

    async def ping():
        if failure == "authentication":
            raise exceptions.AuthenticationError("secret-value")
        if failure == "timeout":
            await asyncio.sleep(10)
        return True

    client = SimpleNamespace(ping=AsyncMock(side_effect=ping), aclose=AsyncMock())
    factory = Mock(return_value=client)
    monkeypatch.setattr(redis.Redis, "from_url", factory)
    check = RedisPing("rediss://user:secret-value@private.example/0", 0.02)
    result = asyncio.run(check.get_result())
    assert bool(result.error) == bool(failure)
    assert "secret-value" not in str(result.error)
    client.aclose.assert_awaited_once()
    assert factory.call_args.kwargs == {"socket_connect_timeout": 0.02, "socket_timeout": 0.02}


def test_disk_capacity_and_absent_mount_never_fall_back(tmp_path, monkeypatch):
    usage = Mock(return_value=SimpleNamespace(total=1000, free=50))
    monkeypatch.setattr("docai.health.shutil.disk_usage", usage)
    check = DiskCapacity(tmp_path, 90, False)
    assert asyncio.run(check.get_result()).error is not None
    assert check.detail == "95.0% used · limit 90%"
    usage.return_value.free = 600
    assert asyncio.run(check.get_result()).error is None
    usage.reset_mock()
    absent = tmp_path / "missing-mount"
    assert asyncio.run(DiskCapacity(absent, 90, False).get_result()).error is not None
    assert not absent.exists()
    usage.assert_not_called()
    monkeypatch.setattr(Path, "is_mount", lambda _: False)
    check = DiskCapacity(tmp_path, 90, True)
    assert asyncio.run(check.get_result()).error is not None
    assert "mount is unavailable" in check.detail
    usage.assert_not_called()
    monkeypatch.setattr(Path, "is_mount", lambda _: True)
    assert asyncio.run(check.get_result()).error is None


@pytest.mark.parametrize(
    "name,value",
    [
        ("DOCAI_HEALTH_TIMEOUT_SECONDS", 0),
        ("DOCAI_HEALTH_DISK_MAX_USED_PERCENT", 101),
        ("DOCAI_HEALTH_DNS_ENDPOINTS", []),
        ("DOCAI_HEALTH_DNS_ENDPOINTS", {"bad key": "private.example"}),
        ("DOCAI_HEALTH_DNS_ENDPOINTS", {"identity": "https://"}),
    ],
)
def test_bad_probe_configuration_is_caught_by_django_checks(diagnostics, name, value):
    setattr(diagnostics, name, value)
    errors = health_configuration_checks(None)
    assert errors and all(error.id == "docai.E013" for error in errors)
    assert "private.example" not in str(errors)
