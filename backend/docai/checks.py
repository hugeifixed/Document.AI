"""Django system checks for the configurable task execution runtime."""

from __future__ import annotations

import importlib.util
import platform

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

from config.celery_runtime import broker_scheme, filesystem_path_error, worker_pool_error


@register(Tags.compatibility)
def task_runtime_checks(app_configs, **kwargs):
    del app_configs, kwargs
    runner = settings.DOCAI.get("TASK_RUNNER", "")
    if runner not in {"sync", "thread", "celery"}:
        return [
            Error(
                "DOCAI_TASK_RUNNER must be sync, thread, or celery.",
                id="docai.E001",
            )
        ]
    if runner != "celery":
        return []

    issues = []
    if importlib.util.find_spec("celery") is None:
        issues.append(
            Error(
                'Celery is selected but not installed. Install the optional extra with `uv pip install -e ".[celery]"`.',
                id="docai.E002",
            )
        )

    broker_url = getattr(settings, "CELERY_BROKER_URL", "")
    result_backend = getattr(settings, "CELERY_RESULT_BACKEND", "") or ""
    scheme = broker_scheme(broker_url)
    if not scheme:
        issues.append(
            Error(
                "Celery is selected but CELERY_BROKER_URL is empty.",
                id="docai.E003",
            )
        )
    pool = getattr(settings, "CELERY_WORKER_POOL", "")
    if error := worker_pool_error(pool, platform.system()):
        issues.append(Error(error, id="docai.E005"))

    result_scheme = broker_scheme(result_backend)
    if (
        scheme in {"redis", "rediss"} or result_scheme in {"redis", "rediss"}
    ) and importlib.util.find_spec("redis") is None:
        issues.append(
            Error(
                'Redis requires its optional driver. Install with `uv pip install -e ".[celery,redis]"`.',
                id="docai.E006",
            )
        )
    if scheme == "filesystem" and platform.system().lower() == "windows":
        if importlib.util.find_spec("pywintypes") is None:
            issues.append(
                Error(
                    "Kombu's filesystem broker on Windows requires pywin32. Install this project's optional "
                    'Celery dependencies with `uv pip install -e ".[celery]"`.',
                    id="docai.E007",
                )
            )
        issues.append(
            Warning(
                "Celery does not officially support Windows; use the threads or solo pool for local development.",
                id="docai.W001",
            )
        )
        if error := filesystem_path_error(settings.CELERY_FILESYSTEM_DIR, platform.system()):
            issues.append(Error(error, id="docai.E008"))
    if scheme == "filesystem" and not settings.DEBUG:
        issues.append(
            Warning(
                "The filesystem broker supports only a single-host deployment and has no broker HA, heartbeats, "
                "message TTL, or priority. Use Redis or RabbitMQ when those guarantees are required.",
                id="docai.W002",
            )
        )
    if pool != "prefork" and getattr(settings, "CELERY_TASK_SOFT_TIME_LIMIT", None):
        issues.append(
            Warning(
                "The selected worker pool does not enforce Celery soft time limits. Configure timeouts in Azure "
                "and other network clients as well.",
                id="docai.W003",
            )
        )
    soft_limit = getattr(settings, "CELERY_TASK_SOFT_TIME_LIMIT", 0)
    hard_limit = getattr(settings, "CELERY_TASK_TIME_LIMIT", 0)
    if soft_limit <= 0 or hard_limit <= 0 or soft_limit >= hard_limit:
        issues.append(
            Error(
                "CELERY_TASK_SOFT_TIME_LIMIT and CELERY_TASK_TIME_LIMIT must be positive, with soft below hard.",
                id="docai.E009",
            )
        )
    max_retries = getattr(settings, "CELERY_TASK_MAX_RETRIES", -1)
    max_deliveries = getattr(settings, "CELERY_TASK_MAX_DELIVERIES", -1)
    if max_retries < 0 or max_deliveries < max_retries + 1:
        issues.append(
            Error(
                "CELERY_TASK_MAX_RETRIES must be non-negative and CELERY_TASK_MAX_DELIVERIES must allow at least "
                "the initial delivery plus every retry.",
                id="docai.E010",
            )
        )
    return issues
