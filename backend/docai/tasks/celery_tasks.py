"""Thin Celery shims around the database-backed run service."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from django.utils import timezone
from loguru import logger

from config.celery_runtime import TaskRuntimePolicy, current_task_runtime_policy

try:
    from celery import shared_task
    from celery.exceptions import Retry
    from celery.utils.time import get_exponential_backoff_interval
except ImportError:  # celery is an optional extra
    Retry = Exception

    def shared_task(*a: Any, **k: Any):
        def deco(f):
            return f

        return deco


@shared_task(ignore_result=True, queue="docai")
def process_playground_session(
    session_id: str,
    goal: str,
    workflow_type: str,
    refinement: str = "",
    trace_id: str = "",
    attempt_id: str = "",
):
    from docai.services.playground import _process

    _process(session_id, goal, workflow_type, refinement, trace_id, attempt_id)


@shared_task(ignore_result=True, queue="docai")
def cleanup_expired_playground_sessions():
    from docai.services.playground import cleanup_expired

    return cleanup_expired()


def _retry_delay(retries: int, policy: TaskRuntimePolicy) -> int:
    return cast(
        int,
        get_exponential_backoff_interval(
            factor=policy.retry_backoff_seconds,
            retries=retries,
            maximum=policy.retry_backoff_max_seconds,
            full_jitter=True,
        ),
    )


@shared_task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
    queue="docai",
)
def process_run_item(self, item_id: str):
    from docai.models import ITEM_STATUS
    from docai.services.run_execution import (
        finalize_run,
        mark_retry_dispatch_failed,
        process_celery_delivery,
        record_retry_schedule,
    )

    with logger.contextualize(task_name=self.name, task_id=self.request.id or "", item_id=item_id):
        policy = current_task_runtime_policy()
        delivery = process_celery_delivery(
            item_id,
            task_id=self.request.id or "",
            retries=self.request.retries,
        )
        status = delivery.status
        if delivery.retry:
            countdown = _retry_delay(self.request.retries, policy)
            record_retry_schedule(
                item_id,
                attempt=delivery.attempt,
                task_id=delivery.task_id,
                retry_at=timezone.now() + timedelta(seconds=countdown),
            )
            logger.bind(
                event="processing_retry",
                run_id=str(delivery.run_id),
                item_id=item_id,
                task_id=self.request.id,
                attempt=self.request.retries + 1,
                delay_s=countdown,
                error_code=delivery.error_code,
            ).warning("Retry requested")
            try:
                self.retry(
                    exc=RuntimeError(delivery.error_code or "retryable processing failure"),
                    countdown=countdown,
                    max_retries=policy.max_retries,
                )
            except Retry:
                raise
            except Exception as exc:  # noqa: BLE001 -- broker/transport exceptions vary
                mark_retry_dispatch_failed(
                    item_id, attempt=delivery.attempt, task_id=delivery.task_id
                )
                logger.bind(
                    event="retry_dispatch_failed",
                    run_id=str(delivery.run_id),
                    item_id=item_id,
                    task_id=self.request.id,
                    error_type=type(exc).__name__,
                ).error("Retry could not be queued")
                status = ITEM_STATUS.failed

        if status != ITEM_STATUS.running:
            finalize_run(delivery.run_id, only_if_complete=True)
        return status
