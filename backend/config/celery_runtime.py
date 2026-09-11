"""Pure helpers for configuring Celery across development and deployment hosts."""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

SUPPORTED_WORKER_POOLS = frozenset({"prefork", "threads", "solo"})
WINDOWS_MAX_PATH = 260
# Kombu adds a monotonic timestamp, UUID, queue name, separators, and suffix.
# Keep a little extra room beyond the current generated filename format.
CELERY_FILENAME_BUDGET = 80


@dataclass(frozen=True, slots=True)
class TaskRuntimePolicy:
    """Derived task capabilities shared by settings, checks, workers, and admin."""

    runner: str
    broker_url: str
    worker_pool: str
    database_engine: str
    max_workers: int
    worker_concurrency: int
    soft_time_limit: int
    hard_time_limit: int
    max_retries: int
    max_deliveries: int
    retry_backoff_seconds: int
    retry_backoff_max_seconds: int
    filesystem_root: Path
    platform_name: str

    @property
    def broker(self) -> str:
        return broker_scheme(self.broker_url)

    @property
    def is_async(self) -> bool:
        return self.runner == "celery"

    @property
    def uses_sqlite(self) -> bool:
        return "sqlite" in self.database_engine

    @property
    def executor_capacity(self) -> int:
        if self.runner == "sync" or (self.runner == "thread" and self.uses_sqlite):
            return 1
        if self.runner == "thread":
            return max(1, self.max_workers)
        return max(1, self.worker_concurrency)

    @property
    def supports_soft_time_limits(self) -> bool:
        return self.worker_pool == "prefork"

    @property
    def minimum_recovery_age_seconds(self) -> int:
        return max(self.hard_time_limit, self.retry_backoff_max_seconds)


def current_task_runtime_policy(configured_settings: Any | None = None) -> TaskRuntimePolicy:
    """Build the current policy lazily so ``override_settings`` remains effective."""
    if configured_settings is None:
        from django.conf import settings as configured_settings
    runtime_settings = cast(Any, configured_settings)

    return TaskRuntimePolicy(
        runner=str(runtime_settings.DOCAI.get("TASK_RUNNER", "")),
        broker_url=str(getattr(runtime_settings, "CELERY_BROKER_URL", "")),
        worker_pool=str(getattr(runtime_settings, "CELERY_WORKER_POOL", "")),
        database_engine=str(runtime_settings.DATABASES["default"]["ENGINE"]),
        max_workers=int(runtime_settings.DOCAI.get("MAX_WORKERS", 1)),
        worker_concurrency=int(getattr(runtime_settings, "CELERY_WORKER_CONCURRENCY", 1)),
        soft_time_limit=int(getattr(runtime_settings, "CELERY_TASK_SOFT_TIME_LIMIT", 0)),
        hard_time_limit=int(getattr(runtime_settings, "CELERY_TASK_TIME_LIMIT", 0)),
        max_retries=int(getattr(runtime_settings, "CELERY_TASK_MAX_RETRIES", -1)),
        max_deliveries=int(getattr(runtime_settings, "CELERY_TASK_MAX_DELIVERIES", -1)),
        retry_backoff_seconds=int(
            getattr(runtime_settings, "CELERY_TASK_RETRY_BACKOFF_SECONDS", 0)
        ),
        retry_backoff_max_seconds=int(
            getattr(runtime_settings, "CELERY_TASK_RETRY_BACKOFF_MAX_SECONDS", 0)
        ),
        filesystem_root=Path(getattr(runtime_settings, "CELERY_FILESYSTEM_DIR", ".")),
        platform_name=platform.system(),
    )


def broker_scheme(url: str) -> str:
    """Return the normalized transport scheme from a Celery broker URL."""
    return urlsplit(url.strip()).scheme.lower()


def default_worker_pool(platform_name: str | None = None) -> str:
    """Use a Windows-safe pool while retaining prefork on POSIX hosts."""
    host = (platform_name or platform.system()).lower()
    return "threads" if host == "windows" else "prefork"


def worker_pool_error(pool: str, platform_name: str | None = None) -> str | None:
    """Describe an unsupported pool choice, or return ``None`` when valid."""
    normalized = pool.strip().lower()
    if normalized not in SUPPORTED_WORKER_POOLS:
        choices = ", ".join(sorted(SUPPORTED_WORKER_POOLS))
        return f"CELERY_WORKER_POOL must be one of: {choices}."
    host = (platform_name or platform.system()).lower()
    if host == "windows" and normalized == "prefork":
        return "CELERY_WORKER_POOL=prefork is not supported on Windows; use threads or solo."
    return None


def default_filesystem_root(
    data_dir: Path,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Choose a short, user-writable broker location on Windows."""
    host = (platform_name or platform.system()).lower()
    environment = os.environ if environ is None else environ
    if host == "windows":
        base = environment.get("LOCALAPPDATA") or environment.get("TEMP")
        if base:
            return Path(base) / "DocAI" / "celery"
    return data_dir / "celery"


def filesystem_runtime_paths(root: Path) -> dict[str, Path]:
    """Return the directories shared by a local filesystem broker and backend."""
    resolved = root.expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return {
        "messages": resolved / "messages",
        "control": resolved / "control",
    }


def ensure_filesystem_runtime(root: Path) -> dict[str, Path]:
    """Create the filesystem transport directories required by Kombu and Celery."""
    paths = filesystem_runtime_paths(root)
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def filesystem_transport_options(root: Path) -> dict[str, str | bool]:
    """Configure a producer and worker on the same development machine."""
    paths = filesystem_runtime_paths(root)
    return {
        # Both sides use the same spool because the web and worker processes share a host.
        "data_folder_in": str(paths["messages"]),
        "data_folder_out": str(paths["messages"]),
        "control_folder": str(paths["control"]),
        "store_processed": False,
    }


def projected_filesystem_path_length(root: Path) -> int:
    """Estimate the longest broker path in Windows UTF-16 code units."""
    message_path = filesystem_runtime_paths(root)["messages"] / ("x" * CELERY_FILENAME_BUDGET)
    return len(str(message_path).encode("utf-16-le")) // 2


def filesystem_path_error(root: Path, platform_name: str | None = None) -> str | None:
    """Reject filesystem spools that exceed the legacy Windows path boundary."""
    host = (platform_name or platform.system()).lower()
    projected = projected_filesystem_path_length(root)
    if host == "windows" and projected >= WINDOWS_MAX_PATH:
        return (
            f"CELERY_FILESYSTEM_DIR may create {projected}-character paths, exceeding the "
            f"legacy Windows limit of {WINDOWS_MAX_PATH}. Use a shorter path such as "
            r"C:\docai-celery."
        )
    return None
