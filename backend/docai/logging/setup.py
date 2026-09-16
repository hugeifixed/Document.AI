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
    "item_id",
    "document_id",
    "dataset_id",
    "workflow_id",
    "stage",
    "service",
    "items",
    "units",
    "attempt",
    "error_code",
    "exception_type",
    "upstream_status",
    "provider_request_id",
    "provider_attempt",
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


def _console_context(record: Record, *, worker: bool = False) -> str:
    extra = record["extra"]
    labels = {"user_id": "user", "exception_type": "error"}
    if worker:
        labels.update(run_id="run", item_id="item", document_id="doc")
    if extra.get("event") == "http_request":
        keys = ("user_id", "error_code", "exception_type")
    else:
        available = {key for key in extra if not key.startswith("_")}
        available.difference_update({"event", "trace_id", "stdlib_logger", "error_stack"})
        if extra.get("event") != "runtime_startup":
            available.discard("environment")
        if worker:
            available.difference_update({"task_name", "task_id"})
        prioritized = [key for key in _CONTEXT_PRIORITY if key in available]
        keys = (*prioritized, *sorted(available.difference(prioritized)))

    values = []
    for key in keys:
        value = extra.get(key)
        if value is None or value == "":
            continue
        if worker and key in {"run_id", "item_id", "document_id"}:
            value = str(value)[:8]
        values.append(f"{labels.get(key, key)}={_console_value(value)}")
    if extra.get("trace_id"):
        values.append(f"req={extra['trace_id']}")
    return " ".join(values)


def _console_format(record: Record) -> str:
    record["extra"]["_console_context"] = _console_context(record)
    record["extra"]["_console_exception"] = _exception_text(record)
    context = " <dim>{extra[_console_context]}</dim>" if record["extra"]["_console_context"] else ""
    return (
        "<green>{time:HH:mm:ss}</green> <level>{level:<7}</level> "
        f"<level>{{message}}</level>{context}\n{{extra[_console_exception]}}"
    )


def _worker_console_format(record: Record) -> str:
    extra = record["extra"]
    name = str(extra.get("task_name") or "").rsplit(".", 1)[-1]
    task_id = str(extra.get("task_id") or "")
    extra["_worker_label"] = (
        f"{name}[{task_id[:8]}]" if name and task_id else record["process"].name
    )
    extra["_worker_level"] = record["level"].name[0]
    extra["_console_context"] = _console_context(record, worker=True)
    extra["_console_exception"] = _exception_text(record)
    context = " <dim>| {extra[_console_context]}</dim>" if extra["_console_context"] else ""
    return (
        "<green>{time:HH:mm:ss}</green> <level>{extra[_worker_level]}</level> "
        "{extra[_worker_label]} | <level>{message}</level>"
        f"{context}\n{{extra[_console_exception]}}"
    )


def _exception_text(record: Record) -> str:
    exception = record["exception"]
    if not exception:
        return ""
    return sanitize_text(
        "".join(traceback.format_exception(exception.type, exception.value, exception.traceback))
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
        payload["exception"] = {
            "type": exception.type.__name__ if exception.type else "Exception",
            "message": sanitize_text(str(exception.value)),
            "stack": _exception_text(record),
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

    def __init__(self, level: str | int, *, worker: bool = False) -> None:
        super().__init__(level)
        self.worker = worker

    def emit(self, record: logging.LogRecord) -> None:
        # RequestLoggingMiddleware owns HTTP access lines. Keep Django tracebacks,
        # but drop its duplicate status-only messages.
        if getattr(record, "status_code", None) is not None and not record.exc_info:
            return
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # The database-backed service reports business outcomes. Celery's
        # "succeeded" means only that the task returned (even if it returned failed).
        if (
            self.worker
            and record.levelno == logging.INFO
            and record.name
            in {
                "celery.app.trace",
                "celery.worker.strategy",
            }
        ):
            level = "DEBUG"
        context = {"stdlib_logger": record.name}
        if self.worker:
            from celery import current_task

            if current_task and current_task.request.id:
                context.update(task_name=current_task.name, task_id=current_task.request.id)
        frame: FrameType | None = logging.currentframe()
        depth = 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            next_frame = frame.f_back
            frame = next_frame
            depth += 1
        logger.bind(**context).opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _intercept_standard_logs(level: str | int, *, worker: bool = False) -> None:
    handler = _LoguruInterceptHandler(level=level, worker=worker)
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
    if worker:
        logging.root.handlers[:] = [handler]
        logging.root.setLevel(level)
        for name in ("celery", "celery.task", "celery.redirected", "multiprocessing"):
            worker_logger = logging.getLogger(name)
            worker_logger.handlers.clear()
            worker_logger.setLevel(level)
            worker_logger.propagate = True
        numeric_level = logging.getLevelNamesMapping()[level] if isinstance(level, str) else level
        sdk_level = logging.DEBUG if numeric_level <= logging.DEBUG else logging.WARNING
        for name in ("httpx", "httpx2", "httpcore", "azure"):
            logging.getLogger(name).setLevel(sdk_level)


def configure_logging(
    *,
    worker: bool = False,
    level: str | int | None = None,
    logfile: str | None = None,
    colorize: bool | None = None,
) -> None:
    global _configured
    if _configured and not worker:
        return
    _configured = True
    logger.remove()
    logger.configure(patcher=_patch)
    level = level if level is not None else settings.DOCAI_LOG_LEVEL
    if settings.DOCAI_LOG_JSON:
        logger.add(
            logfile or sys.stdout, format=_json_format, level=level, backtrace=False, diagnose=False
        )
    else:
        logger.add(
            logfile or sys.stderr,
            format=_worker_console_format if worker else _console_format,
            colorize=False if logfile else colorize,
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
    _intercept_standard_logs(level, worker=worker)
