"""Optional preparation boundary. Off mode never imports native image libraries.

The context owns temporary outputs; callers publish immutable artifacts before leaving it.
Enhancement warnings are provenance, not errors on successfully processed run items.
"""

from __future__ import annotations

import importlib.util
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from django.conf import settings

from docai.exceptions import (
    DocAIError,
    NormalizationFailed,
    NormalizationLimitExceeded,
    NormalizationUnavailable,
)
from docai.schemas.config import InputQualityConfig

PROFILE = "adaptive-v1"
# Internal implementation revision: invalidate adaptive caches after processing fixes
# without rewriting user configuration or historical run snapshots. Revision 2 removes
# unsafe global contrast stretching. Revision 1 artifacts remain readable.
PROCESSOR_REVISION = 2
SUPPORTED_FORMATS = frozenset({"pdf", "jpeg", "jpg", "png", "tiff", "tif"})


def _availability() -> tuple[bool, str]:
    if not settings.DOCAI_IMAGE_NORMALIZATION_ENABLED:
        return False, "Scan enhancement is disabled for this deployment."
    if any(importlib.util.find_spec(name) is None for name in ("PIL", "cv2", "pypdfium2")):
        return False, "Scan enhancement dependencies are not installed."
    return True, "Scan enhancement is available."


def capabilities() -> dict[str, Any]:
    available, reason = _availability()
    azure = settings.DOCAI["LAYOUT_ADAPTER"] == "azure_di"
    if available and not azure:
        available, reason = False, "Scan enhancement requires Azure Document Intelligence."
    return {
        "image_normalization": {"available": available, "reason": reason, "profile": PROFILE},
        "di_analysis": {"ocr_high_resolution": azure},
    }


def validate_input_quality(config: InputQualityConfig, adapter_key: str) -> None:
    if config.mode == "off":
        return
    if adapter_key != "azure_di":
        raise NormalizationUnavailable("Scan enhancement requires Azure Document Intelligence.")
    available, reason = _availability()
    if not available:
        raise NormalizationUnavailable(reason)


@dataclass
class PreparedInput:
    path: Path
    source_format: str
    selected_pages: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    page_details: list[dict[str, Any]] = field(default_factory=list)


class _CallbackRaised(Exception):
    """Keep cancellation/progress failures outside the native fallback boundary."""

    def __init__(self, original: Exception):
        self.original = original


def _callback(fn: Callable[..., None] | None, *args: int) -> None:
    if fn is not None:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001 — never turn caller cancellation into success
            raise _CallbackRaised(exc) from exc


def _original_is_readable(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return bool(stream.read(1))
    except OSError:
        return False


def _fallback(prepared: PreparedInput, original: Path, source_format: str, exc: Exception) -> None:
    if not _original_is_readable(original):
        raise NormalizationFailed() from exc
    limited = isinstance(exc, (NormalizationLimitExceeded, MemoryError, OverflowError))
    code = "NORMALIZATION_LIMIT_EXCEEDED" if limited else "NORMALIZATION_FALLBACK"
    message = (
        "Scan enhancement exceeded its processing limits. Processing continued with the original document."
        if limited
        else "Scan enhancement could not be completed. Processing continued with the original document."
    )
    prepared.path, prepared.source_format, prepared.selected_pages = original, source_format, None
    # Any partially prepared representations were discarded; never publish their geometry.
    prepared.page_details.clear()
    prepared.summary.update(
        status="fallback",
        pages_adjusted=0,
        pages_skipped=0,
        warnings=[{"code": code, "message": message, "pages": [], "retryable": False}],
    )


@contextmanager
def prepare_input(
    path: Path,
    *,
    source_format: str,
    config: InputQualityConfig,
    check_cancelled: Callable[[], None] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Iterator[PreparedInput]:
    started = time.monotonic()
    prepared = PreparedInput(
        path=path,
        source_format=source_format,
        summary={
            "mode": config.mode,
            "status": "off" if config.mode == "off" else "bypassed",
            "profile": config.profile,
            "pages_examined": 0,
            "pages_adjusted": 0,
            "pages_skipped": 0,
            "duration_ms": 0,
            "warnings": [],
        },
    )
    if config.mode == "off":
        yield prepared
        return
    prepared.summary["processor_revision"] = PROCESSOR_REVISION
    available, reason = _availability()
    if not available:
        raise NormalizationUnavailable(reason)
    if source_format not in SUPPORTED_FORMATS:
        yield prepared
        return
    try:
        from .native import prepare_document
    except (ImportError, OSError) as exc:
        raise NormalizationUnavailable() from exc

    with TemporaryDirectory(prefix="docai-scan-") as directory:
        try:
            _callback(check_cancelled)
            prepare_document(
                prepared,
                directory=Path(directory),
                config=config,
                check_cancelled=lambda: _callback(check_cancelled),
                progress=lambda completed, total: _callback(progress, completed, total),
            )
        except _CallbackRaised as interrupted:
            raise interrupted.original from interrupted
        except DocAIError as exc:
            if exc.error_code == "EMPTY_LAYOUT":
                raise
            _fallback(prepared, path, source_format, exc)
        except Exception as exc:  # noqa: BLE001 — optional native boundary; original remains usable
            _fallback(prepared, path, source_format, exc)
        prepared.summary["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
        # Keep caller/DI exceptions outside the native fallback handler.
        yield prepared
