"""Pure helpers for configuring Celery across development and deployment hosts."""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

SUPPORTED_WORKER_POOLS = frozenset({"prefork", "threads", "solo"})
WINDOWS_MAX_PATH = 260
# Kombu adds a monotonic timestamp, UUID, queue name, separators, and suffix.
# Keep a little extra room beyond the current generated filename format.
CELERY_FILENAME_BUDGET = 80


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
