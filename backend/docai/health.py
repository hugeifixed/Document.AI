"""Optional operational diagnostics, separate from web readiness.

Only deployment settings supply targets. Public results use stable names, never
connection strings, filesystem paths, or provider exception messages.
"""

from __future__ import annotations

import asyncio
import dataclasses
import shutil
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from django.conf import settings
from health_check import DNS, HealthCheck
from health_check.exceptions import ServiceUnavailable


def endpoint_hostname(endpoint: str) -> str:
    """Accept a configured URL or hostname without ever requesting its path."""
    parsed = urlsplit(endpoint if "://" in endpoint else f"//{endpoint}")
    if not parsed.hostname or any(c.isspace() for c in parsed.hostname):
        raise ValueError("An endpoint hostname is required.")
    return parsed.hostname


@dataclasses.dataclass
class DependencyCheck(HealthCheck):
    key: str
    label: str = dataclasses.field(repr=False)
    description: str = dataclasses.field(repr=False)
    probe: HealthCheck = dataclasses.field(repr=False)

    async def run(self) -> None:
        # Delegation retains v4's async/sync execution and error handling, while
        # our own labels keep hostnames and paths out of public OpenMetrics too.
        result = await self.probe.get_result()
        if result.error:
            raise result.error

    @property
    def detail(self) -> str:
        return self.probe.detail if isinstance(self.probe, DiskCapacity) else ""


@dataclasses.dataclass
class EndpointDNS(DNS):
    async def run(self) -> None:
        if not self.hostname:
            raise ServiceUnavailable("Endpoint hostname is not configured.")
        await super().run()


@dataclasses.dataclass
class RedisPing(HealthCheck):
    url: str = dataclasses.field(repr=False)
    timeout: float = dataclasses.field(repr=False)

    async def run(self) -> None:
        # Redis remains removable: local LocMem/filesystem installations never
        # import this optional dependency. A selected but missing client fails visibly.
        try:
            from health_check.contrib.redis import Redis
            from redis.asyncio import Redis as RedisClient
        except ImportError as exc:
            raise ServiceUnavailable("Redis client is not installed.") from exc

        check = Redis(
            client_factory=lambda: RedisClient.from_url(
                self.url, socket_connect_timeout=self.timeout, socket_timeout=self.timeout
            )
        )
        try:
            await asyncio.wait_for(check.run(), timeout=self.timeout)
        except TimeoutError as exc:
            raise ServiceUnavailable("Redis ping timed out.") from exc


@dataclasses.dataclass
class DiskCapacity(HealthCheck):
    path: Path = dataclasses.field(repr=False)
    max_used_percent: float = dataclasses.field(repr=False)
    require_mount: bool = dataclasses.field(repr=False)
    detail: str = dataclasses.field(default="", init=False, repr=False)

    async def run(self) -> None:
        await asyncio.to_thread(self._measure)

    def _measure(self) -> None:
        # Never create a directory or fall back to an ancestor: an absent NAS
        # must not silently pass against the container's writable filesystem.
        self.detail = "Storage directory is unavailable."
        try:
            if not self.path.is_dir():
                raise ServiceUnavailable(self.detail)
            if self.require_mount and not self.path.is_mount():
                self.detail = "Required storage mount is unavailable."
                raise ServiceUnavailable(self.detail)
            usage = shutil.disk_usage(self.path)
            used_percent = 100 * (1 - usage.free / usage.total)
        except OSError as exc:
            raise ServiceUnavailable(self.detail) from exc
        self.detail = f"{used_percent:.1f}% used · limit {self.max_used_percent:g}%"
        if used_percent >= self.max_used_percent:
            raise ServiceUnavailable("Storage capacity threshold exceeded.")


def extended_checks() -> Iterator[DependencyCheck]:
    """Build diagnostics from the current deployment; never accept request targets."""
    if not settings.DOCAI_HEALTH_EXTENDED_ENABLED:
        return
    timeout = settings.DOCAI_HEALTH_TIMEOUT_SECONDS
    yield DependencyCheck(
        "disk",
        "Data disk / NAS",
        "Disk capacity and configured mount availability",
        DiskCapacity(
            Path(settings.DOCAI_HEALTH_DISK_PATH or settings.DOCAI_DATA_DIR),
            settings.DOCAI_HEALTH_DISK_MAX_USED_PERCENT,
            settings.DOCAI_HEALTH_DISK_REQUIRE_MOUNT,
        ),
    )

    targets: list[tuple[str, str, str | list[str]]] = []
    cache = settings.CACHES["default"]
    if cache["BACKEND"] == "django.core.cache.backends.redis.RedisCache":
        targets.append(("redis_cache", "Redis cache", cast(str | list[str], cache["LOCATION"])))
    if settings.DOCAI["TASK_RUNNER"] == "celery":
        targets.append(("redis_broker", "Redis broker", settings.CELERY_BROKER_URL))
    for key, label, locations in targets:
        urls = locations.split(";") if isinstance(locations, str) else locations
        for index, url in enumerate(urls):
            if url.startswith(("redis://", "rediss://")):
                suffix = f"_{index + 1}" if len(urls) > 1 else ""
                yield DependencyCheck(
                    key + suffix,
                    label + (f" {index + 1}" if suffix else ""),
                    "Connection and authentication checked with Redis PING",
                    RedisPing(url, timeout),
                )

    endpoints = {}
    for selected, adapter, endpoint, name in (
        (
            settings.DOCAI["LAYOUT_ADAPTER"],
            "azure_di",
            settings.DOCAI["AZURE_DI_ENDPOINT"],
            "Azure Document Intelligence",
        ),
        (
            settings.DOCAI["LLM_ADAPTER"],
            "azure_openai",
            settings.DOCAI["AZURE_OPENAI_ENDPOINT"],
            "Azure OpenAI",
        ),
    ):
        if selected == adapter:
            endpoints[adapter] = (name, endpoint)
    endpoints.update(
        {
            f"external_{key}": (key.replace("_", " ").title(), endpoint)
            for key, endpoint in settings.DOCAI_HEALTH_DNS_ENDPOINTS.items()
        }
    )
    for key, (label, endpoint) in endpoints.items():
        # A missing active adapter endpoint must fail, not disappear from health.
        try:
            hostname = endpoint_hostname(endpoint)
        except ValueError:
            hostname = ""
        yield DependencyCheck(
            f"dns_{key}",
            f"{label} DNS",
            "Hostname resolution only; authentication and API availability are not tested",
            EndpointDNS(hostname=hostname, timeout=timedelta(seconds=timeout)),
        )
