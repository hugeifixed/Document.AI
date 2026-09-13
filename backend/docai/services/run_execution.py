"""Database-backed run lifecycle and its internal execution adapters.

This module owns dispatch, item claims, retries, interruption recovery,
cancellation, and finalization. Celery and management commands are transports.
"""

from __future__ import annotations

import time
import traceback
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import close_old_connections, transaction
from django.db.models import Count, Q
from django.utils import timezone
from loguru import logger

from config.celery_runtime import current_task_runtime_policy
from docai.exceptions import DocAIError, IntegrationError, RunStateError
from docai.logging.context import new_trace_id, reset_trace_id, set_trace_id
from docai.models import DOC_STATUS, ITEM_STATUS, RUN_STATUS, Document, Run, RunItem
from docai.schemas.config import DIAnalysisConfig, InputQualityConfig
from docai.workflows.base import get_strategy

from . import audit
from .dashboard import invalidate_dashboard
from .layouts import get_or_build_layout


class _ItemCancelled(Exception):
    """Cooperative cancellation; never record it as a normalization failure."""


class _RunItemDispatcher(Protocol):
    is_async: bool

    def dispatch(
        self, item_ids: Iterable[Any], *, run_id: str, task_ids: dict[str, str]
    ) -> bool: ...


class _SyncDispatcher:
    is_async = False

    def dispatch(self, item_ids: Iterable[Any], *, run_id: str, task_ids: dict[str, str]) -> bool:
        del run_id, task_ids
        for item_id in item_ids:
            process_item(item_id)
        return False


class _ThreadDispatcher:
    is_async = False

    def dispatch(self, item_ids: Iterable[Any], *, run_id: str, task_ids: dict[str, str]) -> bool:
        del run_id, task_ids
        ids = list(item_ids)
        policy = current_task_runtime_policy()
        if policy.uses_sqlite:
            for item_id in ids:
                process_item(item_id)
            return False

        def wrapped(item_id: Any) -> str:
            try:
                return process_item(item_id)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(
            max_workers=min(policy.executor_capacity, len(ids) or 1),
            thread_name_prefix="docai",
        ) as executor:
            list(executor.map(wrapped, ids))
        return False


class _CeleryDispatcher:
    is_async = True

    def dispatch(self, item_ids: Iterable[Any], *, run_id: str, task_ids: dict[str, str]) -> bool:
        try:
            import celery  # noqa: F401
        except ImportError as exc:
            raise ImproperlyConfigured(
                'DOCAI_TASK_RUNNER=celery requires `uv pip install -e ".[celery]"`.'
            ) from exc
        from docai.tasks.celery_tasks import process_run_item

        ids = [str(item_id) for item_id in item_ids]
        if not ids:
            return False
        published = 0
        try:
            for item_id in ids:
                process_run_item.apply_async(
                    args=[item_id],
                    task_id=task_ids.get(item_id),
                    retry=True,
                    retry_policy=settings.CELERY_TASK_PUBLISH_RETRY_POLICY,
                )
                published += 1
        except Exception:
            logger.bind(run_id=run_id, published=published, requested=len(ids)).exception(
                "celery dispatch interrupted"
            )
            raise
        policy = current_task_runtime_policy()
        logger.bind(
            run_id=run_id, items=len(ids), broker=policy.broker, pool=policy.worker_pool
        ).info("enqueued to celery")
        return True


def _get_dispatcher() -> _RunItemDispatcher:
    key = current_task_runtime_policy().runner
    dispatchers: dict[str, type[_RunItemDispatcher]] = {
        "sync": _SyncDispatcher,
        "thread": _ThreadDispatcher,
        "celery": _CeleryDispatcher,
    }
    try:
        return dispatchers[key]()
    except KeyError as exc:
        raise ImproperlyConfigured(
            f"Unknown DOCAI_TASK_RUNNER={key!r}; use sync, thread, or celery."
        ) from exc


def _claim_item(item_id, execution_id: str = "") -> tuple[RunItem, bool]:
    """Claim one delivery while suppressing concurrent Celery duplicates."""
    with transaction.atomic():
        item = (
            RunItem.objects.select_for_update()
            .select_related("run", "document", "run__workflow")
            .get(id=item_id)
        )
        run = item.run

        # A repeated broker delivery after a completed task is a no-op. Direct
        # service calls remain useful for deterministic idempotency tests.
        if execution_id and item.status in (
            ITEM_STATUS.succeeded,
            ITEM_STATUS.failed,
            ITEM_STATUS.skipped,
        ):
            return item, False
        if execution_id and item.worker_task_id and item.worker_task_id != execution_id:
            logger.bind(
                run_id=str(run.id),
                item_id=str(item.id),
                task_id=execution_id,
                active_task_id=item.worker_task_id,
            ).warning("duplicate item delivery ignored")
            return item, False

        if execution_id:
            if item.worker_task_id == execution_id:
                item.worker_deliveries += 1
            else:
                item.worker_task_id = execution_id[:64]
                item.worker_deliveries = 1
            if item.worker_deliveries > current_task_runtime_policy().max_deliveries:
                item.status = ITEM_STATUS.failed
                item.stage = "delivery_limit"
                item.error_code = "WORKER_DELIVERY_LIMIT"
                item.error_message = (
                    "Worker delivery limit reached. Retry the failed item manually."
                )
                item.retryable = False
                item.save(
                    update_fields=[
                        "worker_task_id",
                        "worker_deliveries",
                        "status",
                        "stage",
                        "error_code",
                        "error_message",
                        "retryable",
                        "status_changed",
                        "modified",
                    ]
                )
                return item, False

        if run.cancel_requested:
            item.status = ITEM_STATUS.skipped
            item.stage = "cancelled"
            item.save(
                update_fields=[
                    "worker_task_id",
                    "worker_deliveries",
                    "status",
                    "stage",
                    "status_changed",
                    "modified",
                ]
            )
            return item, False

        item.status = ITEM_STATUS.running
        item.attempts += 1
        item.stage = "layout"
        item.error_code = item.error_message = ""
        item.retryable = False
        item.save(
            update_fields=[
                "worker_task_id",
                "worker_deliveries",
                "status",
                "attempts",
                "stage",
                "error_code",
                "error_message",
                "retryable",
                "status_changed",
                "modified",
            ]
        )
    return item, True


def _append_run_warnings(run_id, warnings: list[str]) -> None:
    if not warnings:
        return
    with transaction.atomic():
        locked_run = Run.objects.select_for_update().get(pk=run_id)
        locked_run.warnings = [*(locked_run.warnings or []), *warnings][-200:]
        locked_run.save(update_fields=["warnings", "modified"])


def process_item(
    item_id,
    *,
    execution_id: str = "",
    retry_retryable: bool = False,
) -> str:
    """Process one run item with a database-backed idempotency claim."""
    from .runs import build_context, persist_result

    item, claimed = _claim_item(item_id, execution_id)
    run, doc = item.run, item.document
    token = set_trace_id(item.correlation_id or run.correlation_id or new_trace_id())
    t0 = time.perf_counter()
    if not claimed:
        reset_trace_id(token)
        return item.status
    with logger.contextualize(
        run_id=str(run.pk), item_id=str(item.pk), document_id=str(doc.pk), attempt=item.attempts
    ):
        logger.bind(event="processing_started").info("Processing started")
        prior_document_status = doc.status
        try:
            Document.objects.filter(pk=doc.pk).update(status=DOC_STATUS.processing)
            quality = InputQualityConfig.model_validate(
                run.config_snapshot.get("config", {}).get("input_quality", {})
            )
            analysis = DIAnalysisConfig.model_validate(
                run.config_snapshot.get("config", {}).get("di_analysis", {})
            )
            item.stage = "normalization" if quality.mode == "adaptive" else "layout"
            item.save(update_fields=["stage", "modified"])

            def check_cancelled() -> None:
                if Run.objects.filter(pk=run.pk, cancel_requested=True).exists():
                    raise _ItemCancelled

            def normalization_progress(done: int, total: int) -> None:
                # The stage is the live UI cue. Avoid persisting noisy per-page poll updates.
                check_cancelled()

            layout = get_or_build_layout(
                doc,
                run.layout_adapter,
                input_quality=quality,
                di_analysis=analysis,
                run_item=item,
                check_cancelled=check_cancelled,
                progress=normalization_progress,
            )
            item.stage = "workflow"
            item.save(update_fields=["stage"])
            ctx = build_context(run, run_item=item)
            strategy = get_strategy(ctx.workflow_type)
            res = strategy.process_document(ctx, layout)
            item.stage = "persist"
            item.save(update_fields=["stage"])
            persist_result(run, doc, res, layout)
            item.duration_ms = int((time.perf_counter() - t0) * 1000)
            Document.objects.filter(pk=doc.pk).update(status=DOC_STATUS.processed)
            _append_run_warnings(
                run.pk,
                [f"{doc.original_filename}: {warning}" for warning in res.warnings],
            )
            # The terminal item transition is last so another worker cannot
            # finalize the run while this task still has database work in flight.
            item.status, item.stage, item.retryable = ITEM_STATUS.succeeded, "done", False
            item.save(
                update_fields=[
                    "status",
                    "stage",
                    "retryable",
                    "duration_ms",
                    "status_changed",
                    "modified",
                ]
            )
            logger.bind(
                run_id=str(run.id),
                document_id=str(doc.id),
                stage="done",
                duration_ms=item.duration_ms,
                fields=len(res.fields),
                segments=len(res.segments),
                event="processing_completed",
                warnings=len(res.warnings),
            ).info("Processing completed")
        except _ItemCancelled:
            item.status, item.stage = ITEM_STATUS.skipped, "cancelled"
            item.duration_ms = int((time.perf_counter() - t0) * 1000)
            item.save(
                update_fields=["status", "stage", "duration_ms", "status_changed", "modified"]
            )
            # Upload remains usable; cancellation is an execution outcome.
            Document.objects.filter(pk=doc.pk).update(
                status=prior_document_status
                if prior_document_status != DOC_STATUS.processing
                else DOC_STATUS.validated
            )
            logger.bind(event="processing_cancelled", duration_ms=item.duration_ms).info(
                "Processing cancelled"
            )
        except DocAIError as exc:
            _fail(
                item,
                exc.error_code,
                exc.message,
                exc.retryable,
                t0,
                queue_for_retry=retry_retryable and exc.retryable,
            )
        except Exception as exc:  # noqa: BLE001
            logger.bind(run_id=str(run.id), document_id=str(doc.id), stage=item.stage).debug(
                "item failed: {}", type(exc).__name__
            )
            logger.debug(traceback.format_exc())
            _fail(
                item,
                "INTERNAL_ERROR",
                "Processing failed unexpectedly. Reference the trace id when reporting.",
                False,
                t0,
                queue_for_retry=False,
            )
        finally:
            with suppress(ValueError):
                reset_trace_id(token)
        return item.status


def _fail(item, code, message, retryable, t0, *, queue_for_retry=False):
    failed_stage = item.stage
    Document.objects.filter(pk=item.document_id).update(status=DOC_STATUS.failed)
    item.status = ITEM_STATUS.queued if queue_for_retry else ITEM_STATUS.failed
    if queue_for_retry:
        item.stage = "retry_wait"
    item.error_code, item.error_message, item.retryable = code, message[:2000], retryable
    item.duration_ms = int((time.perf_counter() - t0) * 1000)
    item.save(
        update_fields=[
            "status",
            "stage",
            "error_code",
            "error_message",
            "retryable",
            "duration_ms",
            "status_changed",
            "modified",
        ]
    )
    logger.bind(
        event="processing_failed",
        stage=failed_stage,
        error_code=code,
        retryable=retryable,
        retry_pending=queue_for_retry,
        duration_ms=item.duration_ms,
    ).log("WARNING" if queue_for_retry else "ERROR", "Processing failed")


def _record_local_execution_interruption(run_id) -> int:
    """Make unfinished inline work visible and retryable after an executor failure."""
    now = timezone.now()
    message = "Local execution stopped before this document completed. It is safe to retry."
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run_id)
        interrupted = run.items.filter(status__in=(ITEM_STATUS.queued, ITEM_STATUS.running)).update(
            status=ITEM_STATUS.failed,
            stage="execution_interrupted",
            error_code="EXECUTION_INTERRUPTED",
            error_message=message,
            retryable=True,
            status_changed=now,
            modified=now,
        )
        run.stage = "execution_interrupted"
        run.errors = [
            *(run.errors or []),
            "Local execution was interrupted; unfinished documents are safe to retry.",
        ][-200:]
        run.save(update_fields=["stage", "errors", "modified"])
    finalize_run(run_id, only_if_complete=True)
    return interrupted


@dataclass(frozen=True, slots=True)
class CeleryDelivery:
    """Transport-neutral result telling the Celery shim whether to retry."""

    run_id: Any
    status: str
    retry: bool
    error_code: str


def process_celery_delivery(item_id: str, *, task_id: str, retries: int) -> CeleryDelivery:
    """Process a Celery delivery and derive its retry decision from durable state."""
    policy = current_task_runtime_policy()
    retry_available = retries < policy.max_retries
    status = process_item(
        item_id,
        execution_id=task_id,
        retry_retryable=retry_available,
    )
    item = RunItem.objects.only("run_id", "retryable", "error_code", "worker_task_id").get(
        pk=item_id
    )
    return CeleryDelivery(
        run_id=item.run_id,
        status=status,
        retry=(
            status == ITEM_STATUS.queued
            and item.retryable
            and retry_available
            and item.worker_task_id == task_id
        ),
        error_code=item.error_code,
    )


def mark_retry_dispatch_failed(item_id: str) -> None:
    """Make a broker failure visible without letting a queued item stall forever."""
    now = timezone.now()
    RunItem.objects.filter(pk=item_id, status=ITEM_STATUS.queued).update(
        status=ITEM_STATUS.failed,
        stage="retry_dispatch_failed",
        status_changed=now,
        modified=now,
    )


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    recovered_items: int
    affected_runs: int


def recover_stalled_items(age_seconds: int | None = None) -> RecoveryResult:
    """Recover stale deliveries and finalize runs through the normal lifecycle seam."""
    policy = current_task_runtime_policy()
    minimum_age = policy.minimum_recovery_age_seconds
    if age_seconds is None:
        age_seconds = minimum_age + 300
    if age_seconds <= minimum_age:
        raise ValueError(
            "The recovery age must exceed both the hard task limit and maximum retry backoff."
        )

    now = timezone.now()
    stale = RunItem.objects.filter(
        Q(status=ITEM_STATUS.running) | Q(status=ITEM_STATUS.queued, stage="retry_wait"),
        status_changed__lt=now - timedelta(seconds=age_seconds),
    )
    run_ids = list(stale.values_list("run_id", flat=True).distinct())
    recovered = stale.update(
        status=ITEM_STATUS.failed,
        stage="worker_lost",
        error_code="WORKER_LOST",
        error_message=(
            "The worker stopped before this item or its retry completed. It is safe to retry."
        ),
        retryable=True,
        status_changed=now,
        modified=now,
    )
    for run_id in run_ids:
        finalize_run(run_id, only_if_complete=True)
    return RecoveryResult(recovered_items=recovered, affected_runs=len(run_ids))


def execute_run(run_id, only_failed: bool = False) -> Run:
    """Drive all items through the configured task runner, then finalize."""
    dispatcher = _get_dispatcher()
    with transaction.atomic():
        run = Run.objects.select_for_update().get(id=run_id)
        if only_failed and not run.items.filter(status=ITEM_STATUS.failed).exists():
            raise RunStateError("This run has no failed items to retry.")
        if run.status == RUN_STATUS.succeeded or (
            run.status == RUN_STATUS.cancelled and not only_failed
        ):
            raise RunStateError()
        if run.status == RUN_STATUS.running and run.stage != "dispatch_failed":
            raise RunStateError("This run is already executing.")
        run.status, run.started_at, run.stage = (
            RUN_STATUS.running,
            run.started_at or timezone.now(),
            "processing",
        )
        run.cancel_requested = False
        run.save(
            update_fields=[
                "status",
                "started_at",
                "stage",
                "cancel_requested",
                "status_changed",
                "modified",
            ]
        )
        qs = (
            run.items.filter(status=ITEM_STATUS.failed)
            if only_failed
            else run.items.filter(status__in=(ITEM_STATUS.queued, ITEM_STATUS.failed))
        )
        items = list(qs.only("id", "status"))
        ids = [item.id for item in items]
        task_ids: dict[str, str] = {}
        if dispatcher.is_async:
            changed_at = timezone.now()
            for item in items:
                task_id = uuid4().hex
                task_ids[str(item.id)] = task_id
                item.status = ITEM_STATUS.queued
                item.stage = "queued"
                item.worker_task_id = task_id
                item.worker_deliveries = 0
                item.status_changed = changed_at
                item.modified = changed_at
            RunItem.objects.bulk_update(
                items,
                [
                    "status",
                    "stage",
                    "worker_task_id",
                    "worker_deliveries",
                    "status_changed",
                    "modified",
                ],
            )
    try:
        scheduled = dispatcher.dispatch(
            ids,
            run_id=str(run.id),
            task_ids=task_ids if dispatcher.is_async else {},
        )
    except Exception as exc:
        if dispatcher.is_async:
            with transaction.atomic():
                run = Run.objects.select_for_update().get(pk=run.pk)
                if run.stage != "finalized":
                    run.stage = "dispatch_failed"
                    run.errors = [
                        *(run.errors or []),
                        "The worker queue could not accept every item. Retry execution after restoring the broker.",
                    ][-200:]
                    run.save(update_fields=["stage", "errors", "modified"])
            logger.bind(run_id=str(run.id), error_type=type(exc).__name__).error(
                "celery dispatch failed"
            )
            raise IntegrationError(
                "Document processing could not be queued. Restore the worker broker and retry execution."
            ) from exc
        try:
            interrupted = _record_local_execution_interruption(run.id)
        except Exception as recovery_exc:  # noqa: BLE001
            logger.bind(
                run_id=str(run.id),
                error_type=type(exc).__name__,
                recovery_error_type=type(recovery_exc).__name__,
            ).exception("local run interruption could not be recorded")
        else:
            logger.bind(
                run_id=str(run.id),
                error_type=type(exc).__name__,
                interrupted_items=interrupted,
            ).error("local run interrupted")
        raise IntegrationError(
            "Document processing was interrupted. Open the run and retry its failed documents.",
            error_code="EXECUTION_INTERRUPTED",
        ) from exc
    if dispatcher.is_async and scheduled:
        run.refresh_from_db()
        return run
    if dispatcher.is_async and run.items.filter(status=ITEM_STATUS.running).exists():
        run.refresh_from_db()
        return run
    return finalize_run(run.id)


@transaction.atomic
def finalize_run(run_id, *, only_if_complete: bool = False) -> Run:
    """Finalize exactly once after every item reaches a terminal state."""
    run = Run.objects.select_for_update().get(id=run_id)
    states = (
        ITEM_STATUS.succeeded,
        ITEM_STATUS.failed,
        ITEM_STATUS.skipped,
        ITEM_STATUS.queued,
        ITEM_STATUS.running,
    )
    observed = {
        row["status"]: row["total"]
        for row in run.items.values("status").annotate(total=Count("id"))
    }
    counts = {state: observed.get(state, 0) for state in states}
    if counts[ITEM_STATUS.queued] or counts[ITEM_STATUS.running]:
        if only_if_complete:
            return run
        raise RunStateError("A run cannot be finalized while items are queued or running.")
    if run.stage == "finalized" and run.status in {
        RUN_STATUS.succeeded,
        RUN_STATUS.failed,
        RUN_STATUS.partial,
        RUN_STATUS.cancelled,
    }:
        return run
    run.processed_items = counts[ITEM_STATUS.succeeded] + counts[ITEM_STATUS.failed]
    run.failed_items = counts[ITEM_STATUS.failed]
    if run.cancel_requested:
        run.status = RUN_STATUS.cancelled
    elif counts[ITEM_STATUS.failed] and counts[ITEM_STATUS.succeeded]:
        run.status = RUN_STATUS.partial
    elif counts[ITEM_STATUS.failed]:
        run.status = RUN_STATUS.failed
    else:
        run.status = RUN_STATUS.succeeded
    run.finished_at, run.stage = timezone.now(), "finalized"
    from .evaluation import metrics_for_run

    try:
        run.metrics = metrics_for_run(run)
    except Exception as exc:  # noqa: BLE001
        logger.bind(run_id=str(run.id)).warning("metrics failed: {}", type(exc).__name__)
        run.metrics = {"error": "metrics could not be computed"}
    run.save(
        update_fields=[
            "processed_items",
            "failed_items",
            "status",
            "finished_at",
            "stage",
            "metrics",
            "status_changed",
            "modified",
        ]
    )
    audit.record(
        run.created_by,
        "run.finished",
        run,
        after={"status": run.status, "processed": run.processed_items, "failed": run.failed_items},
    )
    return run


@transaction.atomic
def request_cancel(run: Run, user=None) -> Run:
    """Stop unclaimed work now and let already-running items finish safely."""
    run = Run.objects.select_for_update().get(pk=run.pk)
    if run.status not in (RUN_STATUS.queued, RUN_STATUS.running):
        raise RunStateError()

    now = timezone.now()
    run.items.filter(status=ITEM_STATUS.queued).update(
        status=ITEM_STATUS.skipped,
        stage="cancelled",
        error_code="",
        error_message="",
        retryable=False,
        status_changed=now,
        modified=now,
    )
    run.cancel_requested = True
    run.stage = "cancelling"
    run.updated_by = user
    run.save(update_fields=["cancel_requested", "stage", "updated_by", "modified"])
    audit.record(user, "run.cancel_requested", run)
    invalidate_dashboard(run.project_id)

    if not run.items.filter(status=ITEM_STATUS.running).exists():
        return finalize_run(run.pk)
    return run


def progress(run: Run) -> dict:
    items = run.items.values_list("status", flat=True)
    c = Counter(items)
    done = c[ITEM_STATUS.succeeded] + c[ITEM_STATUS.failed] + c[ITEM_STATUS.skipped]
    est = None
    if run.started_at and done and run.total_items > done and run.status == RUN_STATUS.running:
        elapsed = (timezone.now() - run.started_at).total_seconds()
        est = round(elapsed / done * (run.total_items - done))
    return {
        "total": run.total_items,
        "succeeded": c[ITEM_STATUS.succeeded],
        "failed": c[ITEM_STATUS.failed],
        "skipped": c[ITEM_STATUS.skipped],
        "queued": c[ITEM_STATUS.queued],
        "running": c[ITEM_STATUS.running],
        "remaining": run.total_items - done,
        "stage": run.stage,
        "estimated_seconds_remaining": est,
    }
