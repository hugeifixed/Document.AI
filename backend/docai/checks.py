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
        return [Error(
            "DOCAI_TASK_RUNNER must be sync, thread, or celery.",
            id="docai.E001",
        )]
    if runner != "celery":
        return []

    issues = []
    if importlib.util.find_spec("celery") is None:
        issues.append(Error(
            'Celery is selected but not installed. Install the optional extra with `uv pip install -e ".[celery]"`.',
            id="docai.E002",
        ))

    broker_url = getattr(settings, "CELERY_BROKER_URL", "")
    result_backend = getattr(settings, "CELERY_RESULT_BACKEND", "")
    scheme = broker_scheme(broker_url)
    if not scheme:
        issues.append(Error(
            "Celery is selected but CELERY_BROKER_URL is empty.",
            id="docai.E003",
        ))
    if not result_backend:
        issues.append(Error(
            "Celery runs require CELERY_RESULT_BACKEND because run finalization uses a chord.",
            id="docai.E004",
        ))

    pool = getattr(settings, "CELERY_WORKER_POOL", "")
    if error := worker_pool_error(pool, platform.system()):
        issues.append(Error(error, id="docai.E005"))

    if scheme in {"redis", "rediss"} and importlib.util.find_spec("redis") is None:
        issues.append(Error(
            'The Redis broker requires the Redis driver from the optional `celery` extra.',
            id="docai.E006",
        ))
    if scheme == "filesystem" and platform.system().lower() == "windows":
        if importlib.util.find_spec("pywintypes") is None:
            issues.append(Error(
                "The filesystem broker on Windows requires pywin32 from the optional `celery` extra.",
                id="docai.E007",
            ))
        issues.append(Warning(
            "Celery does not officially support Windows; use the threads or solo pool for local development.",
            id="docai.W001",
        ))
        if error := filesystem_path_error(
            settings.CELERY_FILESYSTEM_DIR, platform.system()
        ):
            issues.append(Error(error, id="docai.E008"))
    if scheme == "filesystem" and not settings.DEBUG:
        issues.append(Warning(
            "The filesystem broker is intended for single-host development. Configure Redis for deployment.",
            id="docai.W002",
        ))
    return issues
