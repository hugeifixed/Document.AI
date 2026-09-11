"""Compact local logs and flat JSON records with safe request correlation."""

from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from types import FrameType
from typing import TYPE_CHECKING, Any

from django.conf import settings
from loguru import logger

if TYPE_CHECKING:
    from loguru import Record

from .context import get_trace_id
from .sanitize import sanitize_extra, sanitize_text

_configured = False
_SAFE_CONSOLE_VALUE = re.compile(r"^[\w./:@+-]+$")
_CONTEXT_PRIORITY = (
    "run_id",
    "document_id",
    "dataset_id",
    "workflow_id",
    "stage",
    "service",
    "items",
    "units",
    "attempt",
    "error_code",
    "delay_s",
    "duration_ms",
)


def _patch(record: Record) -> None:
    record["extra"]["trace_id"] = record["extra"].get("trace_id") or get_trace_id()
    record["extra"].setdefault("environment", settings.DOCAI_ENVIRONMENT)
    record["extra"] = sanitize_extra(record["extra"])
    record["message"] = sanitize_text(record["message"])


def _console_value(value: Any) -> str:
    if isinstance(value, str) and _SAFE_CONSOLE_VALUE.fullmatch(value):
        return value
    rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return rendered if len(rendered) <= 160 else f"{rendered[:157]}..."


def _console_context(record: Record) -> str:
    extra = record["extra"]
    labels = {"user_id": "user", "exception_type": "error"}
    if extra.get("event") == "http_request":
        keys = ("user_id", "exception_type")
    else:
        available = {key for key in extra if not key.startswith("_")}
        available.difference_update({"event", "trace_id"})
        prioritized = [key for key in _CONTEXT_PRIORITY if key in available]
        keys = (*prioritized, *sorted(available.difference(prioritized)))

    values = [
        f"{labels.get(key, key)}={_console_value(extra[key])}"
        for key in keys
        if extra.get(key) is not None and extra.get(key) != ""
    ]
    if extra.get("trace_id"):
        values.append(f"req={extra['trace_id']}")
    return " ".join(values)


def _console_format(record: Record) -> str:
    record["extra"]["_console_context"] = _console_context(record)
    context = " <dim>{extra[_console_context]}</dim>" if record["extra"]["_console_context"] else ""
    return (
        "<green>{time:HH:mm:ss}</green> <level>{level:<7}</level> "
        f"<level>{{message}}</level>{context}\n{{exception}}"
    )


def _json_payload(record: Record) -> dict[str, Any]:
    extra = {key: value for key, value in record["extra"].items() if not key.startswith("_")}
    payload: dict[str, Any] = {
        "ts": record["time"].isoformat(),
        "level": record["level"].name,
        "logger": f"{record['name']}:{record['function']}:{record['line']}",
        "message": record["message"],
        "process_id": record["process"].id,
        "thread_id": record["thread"].id,
        **extra,
    }
    exception = record["exception"]
    if exception:
        stack = "".join(
            traceback.format_exception(
                exception.type,
                exception.value,
                exception.traceback,
            )
        )
        payload["exception"] = {
            "type": exception.type.__name__ if exception.type else "Exception",
            "message": sanitize_text(str(exception.value)),
            "stack": sanitize_text(stack),
        }
    return payload


def _json_format(record: Record) -> str:
    record["extra"]["_serialized"] = json.dumps(
        _json_payload(record),
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return "{extra[_serialized]}\n"


class _LoguruInterceptHandler(logging.Handler):
    """Send standard-library records through the same Loguru sinks."""

    def emit(self, record: logging.LogRecord) -> None:
        # RequestLoggingMiddleware owns HTTP access lines. Keep Django tracebacks,
        # but drop its duplicate status-only messages.
        if getattr(record, "status_code", None) is not None and not record.exc_info:
            return
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame: FrameType | None = logging.currentframe()
        depth = 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            next_frame = frame.f_back
            frame = next_frame
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _intercept_standard_logs(level: str) -> None:
    handler = _LoguruInterceptHandler(level=level)
    for name, candidate in logging.root.manager.loggerDict.items():
        if name.startswith("django.") and isinstance(candidate, logging.Logger):
            candidate.handlers.clear()
            candidate.propagate = True
    django_logger = logging.getLogger("django")
    django_logger.handlers[:] = [handler]
    django_logger.setLevel(level)
    django_logger.propagate = False
    logging.captureWarnings(True)
    warnings_logger = logging.getLogger("py.warnings")
    warnings_logger.handlers[:] = [handler]
    warnings_logger.setLevel(level)
    warnings_logger.propagate = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True
    logger.remove()
    logger.configure(patcher=_patch)
    level = settings.DOCAI_LOG_LEVEL
    if settings.DOCAI_LOG_JSON:
        logger.add(sys.stdout, format=_json_format, level=level, backtrace=False, diagnose=False)
    else:
        logger.add(
            sys.stderr,
            format=_console_format,
            colorize=True,
            level=level,
            backtrace=False,
            diagnose=False,
        )

    log_dir = settings.DOCAI_LOG_DIR
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "docai.log",
            format=_json_format,
            rotation="20 MB",
            retention=10,
            enqueue=True,
            encoding="utf8",
            level=level,
            backtrace=False,
            diagnose=False,
        )
    except OSError:
        pass
    _intercept_standard_logs(level)
