"""Thin Celery shims around the database-backed run service."""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from loguru import logger

try:
    from celery import shared_task
    from celery.exceptions import Retry
    from celery.utils.time import get_exponential_backoff_interval
except ImportError:  # celery is an optional extra
    Retry = Exception  # type: ignore[misc,assignment]

    def shared_task(*a, **k):  # type: ignore
        def deco(f):
            return f

        return deco


def _retry_delay(retries: int) -> int:
    return get_exponential_backoff_interval(
        factor=settings.CELERY_TASK_RETRY_BACKOFF_SECONDS,
        retries=retries,
        maximum=settings.CELERY_TASK_RETRY_BACKOFF_MAX_SECONDS,
        full_jitter=True,
    )


@shared_task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
    queue="docai",
)
def process_run_item(self, item_id: str):
    from docai.models import ITEM_STATUS, RunItem
    from docai.services.runs import finalize_run, process_item

    retry_available = self.request.retries < settings.CELERY_TASK_MAX_RETRIES
    status = process_item(
        item_id,
        execution_id=self.request.id or "",
        retry_retryable=retry_available,
    )
    item = RunItem.objects.only("run_id", "retryable", "error_code", "worker_task_id").get(
        pk=item_id
    )

    if (
        status == ITEM_STATUS.queued
        and item.retryable
        and retry_available
        and item.worker_task_id == (self.request.id or "")
    ):
        countdown = _retry_delay(self.request.retries)
        logger.bind(
            run_id=str(item.run_id),
            item_id=item_id,
            task_id=self.request.id,
            attempt=self.request.retries + 1,
            delay_s=countdown,
            error_code=item.error_code,
        ).warning("item queued for retry")
        try:
            self.retry(
                exc=RuntimeError(item.error_code or "retryable processing failure"),
                countdown=countdown,
                max_retries=settings.CELERY_TASK_MAX_RETRIES,
            )
        except Retry:
            raise
        except Exception as exc:  # noqa: BLE001 -- broker/transport exceptions vary
            RunItem.objects.filter(pk=item_id, status=ITEM_STATUS.queued).update(
                status=ITEM_STATUS.failed,
                stage="retry_dispatch_failed",
                status_changed=timezone.now(),
            )
            logger.bind(
                run_id=str(item.run_id),
                item_id=item_id,
                task_id=self.request.id,
                error_type=type(exc).__name__,
            ).error("item retry could not be queued")
            status = ITEM_STATUS.failed

    if status != ITEM_STATUS.running:
        finalize_run(item.run_id, only_if_complete=True)
    return status
