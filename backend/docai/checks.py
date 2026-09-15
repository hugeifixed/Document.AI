"""Django system checks for the configurable task execution runtime."""

from __future__ import annotations

import importlib.util

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

from config.celery_runtime import (
    broker_scheme,
    current_task_runtime_policy,
    filesystem_path_error,
    worker_pool_error,
)


@register(Tags.compatibility)
def headless_contract_checks(app_configs, **kwargs):
    """Reject settings that weaken the public idempotency guarantee."""
    del app_configs, kwargs
    issues: list[Error] = []
    if settings.DOCAI["IDEMPOTENCY_RETENTION_DAYS"] < 30:
        issues.append(
            Error(
                "DOCAI_IDEMPOTENCY_RETENTION_DAYS must be at least 30.",
                id="docai.E011",
            )
        )
    if settings.DOCAI["INVOCATION_LEASE_SECONDS"] <= 0:
        issues.append(
            Error(
                "DOCAI_INVOCATION_LEASE_SECONDS must be positive.",
                id="docai.E012",
            )
        )
    return issues


@register(Tags.compatibility)
def task_runtime_checks(app_configs, **kwargs):
    del app_configs, kwargs
    policy = current_task_runtime_policy()
    if policy.runner not in {"sync", "thread", "celery"}:
        return [
            Error(
                "DOCAI_TASK_RUNNER must be sync, thread, or celery.",
                id="docai.E001",
            )
        ]
    if policy.runner != "celery":
        return []

    issues: list[Error | Warning] = []
    if importlib.util.find_spec("celery") is None:
        issues.append(
            Error(
                'Celery is selected but not installed. Install the optional extra with `uv pip install -e ".[celery]"`.',
                id="docai.E002",
            )
        )

    result_backend = getattr(settings, "CELERY_RESULT_BACKEND", "") or ""
    scheme = policy.broker
    if not scheme:
        issues.append(
            Error(
                "Celery is selected but CELERY_BROKER_URL is empty.",
                id="docai.E003",
            )
        )
    if error := worker_pool_error(policy.worker_pool, policy.platform_name):
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
    if scheme == "filesystem" and policy.platform_name.lower() == "windows":
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
        if error := filesystem_path_error(policy.filesystem_root, policy.platform_name):
            issues.append(Error(error, id="docai.E008"))
    if scheme == "filesystem" and not settings.DEBUG:
        issues.append(
            Warning(
                "The filesystem broker supports only a single-host deployment and has no broker HA, heartbeats, "
                "message TTL, or priority. Use Redis or RabbitMQ when those guarantees are required.",
                id="docai.W002",
            )
        )
    if not policy.supports_soft_time_limits and policy.soft_time_limit:
        issues.append(
            Warning(
                "The selected worker pool does not enforce Celery soft time limits. Configure timeouts in Azure "
                "and other network clients as well.",
                id="docai.W003",
            )
        )
    if (
        policy.soft_time_limit <= 0
        or policy.hard_time_limit <= 0
        or policy.soft_time_limit >= policy.hard_time_limit
    ):
        issues.append(
            Error(
                "CELERY_TASK_SOFT_TIME_LIMIT and CELERY_TASK_TIME_LIMIT must be positive, with soft below hard.",
                id="docai.E009",
            )
        )
    if policy.max_retries < 0 or policy.max_deliveries < policy.max_retries + 1:
        issues.append(
            Error(
                "CELERY_TASK_MAX_RETRIES must be non-negative and CELERY_TASK_MAX_DELIVERIES must allow at least "
                "the initial delivery plus every retry.",
                id="docai.E010",
            )
        )
    return issues
