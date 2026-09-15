"""Database-backed run lifecycle and its internal execution adapters.

This module owns dispatch, item claims, retries, interruption recovery,
cancellation, and finalization. Celery and management commands are transports.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import BoundedSemaphore, Lock
from typing import Any, Protocol, cast
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import close_old_connections, transaction
from django.db.models import Case, Count, IntegerField, Max, Q, When
from django.utils import timezone
from loguru import logger

from config.celery_runtime import current_task_runtime_policy
from docai.exceptions import DocAIError, IntegrationError, RunStateError
from docai.logging.context import new_trace_id, reset_trace_id, set_trace_id
from docai.logging.sanitize import exception_context
from docai.models import DOC_STATUS, ITEM_STATUS, RUN_STATUS, Document, Run, RunItem
from docai.schemas.config import DIAnalysisConfig, InputQualityConfig
from docai.schemas.progress import ProcessingProgress, ProgressOperation, ProgressPhase
from docai.workflows.base import get_strategy

from . import audit
from .layouts import get_or_build_layout
from .run_progress import ProgressRecorder, snapshot


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


def _get_dispatcher(runner: str | None = None) -> _RunItemDispatcher:
    key = runner or current_task_runtime_policy().runner
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


_LOCAL_QUEUED_STAGE = "local_queued"
_DISPATCH_FAILED_STAGE = "dispatch_failed"
_LOCAL_RUN_QUEUE_CAPACITY = 32


class _LocalRunCoordinator:
    """Serialize locally accepted HTTP runs through one process-level worker.

    A run may still use ``DOCAI_MAX_WORKERS`` for its document items on a
    server database. Keeping one coordinator prevents concurrent HTTP requests
    from multiplying those pools. This is intentionally best-effort local
    infrastructure; durable deployments use Celery.
    """

    def __init__(self, capacity: int = _LOCAL_RUN_QUEUE_CAPACITY) -> None:
        self._lock = Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._capacity = BoundedSemaphore(capacity)

    def submit(self, run_id: Any, *, only_failed: bool, runner: str) -> None:
        if not self._capacity.acquire(blocking=False):
            raise RuntimeError("The local run queue is full.")
        try:
            with self._lock:
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(
                        max_workers=1,
                        thread_name_prefix="docai-run",
                    )
                future = self._executor.submit(
                    _execute_scheduled_local_run,
                    run_id,
                    only_failed=only_failed,
                    runner=runner,
                )
        except Exception:
            self._capacity.release()
            raise
        future.add_done_callback(lambda _: self._capacity.release())


_local_run_coordinator = _LocalRunCoordinator()


def _execute_scheduled_local_run(run_id: Any, *, only_failed: bool, runner: str) -> None:
    """Run accepted local work outside the request and isolate DB connections."""
    close_old_connections()
    try:
        execute_run(
            run_id,
            only_failed=only_failed,
            _scheduled_local=True,
            _runner=runner,
        )
    except Exception as exc:  # noqa: BLE001 -- state is persisted by execute_run/recovery
        logger.bind(run_id=str(run_id), error_type=type(exc).__name__).exception(
            "scheduled local run failed"
        )
    finally:
        close_old_connections()


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
                now = timezone.now()
                item.status = ITEM_STATUS.failed
                item.stage = "delivery_limit"
                item.error_code = "WORKER_DELIVERY_LIMIT"
                item.error_message = (
                    "Worker delivery limit reached. Retry the failed item manually."
                )
                item.retryable = False
                item.processing_progress = snapshot(
                    "complete", "failed", now=now, previous=item.processing_progress
                )
                item.progress_updated_at = now
                item.save(
                    update_fields=[
                        "worker_task_id",
                        "worker_deliveries",
                        "status",
                        "stage",
                        "error_code",
                        "error_message",
                        "retryable",
                        "processing_progress",
                        "progress_updated_at",
                        "status_changed",
                        "modified",
                    ]
                )
                return item, False

        if run.cancel_requested:
            now = timezone.now()
            item.status = ITEM_STATUS.skipped
            item.stage = "cancelled"
            item.processing_progress = snapshot(
                "complete", "cancelled", now=now, previous=item.processing_progress
            )
            item.progress_updated_at = now
            item.save(
                update_fields=[
                    "worker_task_id",
                    "worker_deliveries",
                    "status",
                    "stage",
                    "processing_progress",
                    "progress_updated_at",
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
        now = timezone.now()
        item.processing_progress = snapshot("queued", "queued", now=now)
        item.progress_updated_at = now
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
                "processing_progress",
                "progress_updated_at",
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
    progress_recorder = ProgressRecorder(item.pk, item.attempts, item.worker_task_id)
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
                check_cancelled()
                progress_recorder.record(
                    "preparing_scans",
                    "preparing_scans",
                    completed=done,
                    total=total,
                    unit="pages",
                    force=done >= total,
                )

            def layout_progress(phase: str, operation: str, **kwargs) -> None:
                progress_recorder.record(
                    cast(ProgressPhase, phase),
                    cast(ProgressOperation, operation),
                    force=True,
                    **kwargs,
                )

            layout = get_or_build_layout(
                doc,
                run.layout_adapter,
                input_quality=quality,
                di_analysis=analysis,
                run_item=item,
                check_cancelled=check_cancelled,
                progress=normalization_progress,
                milestone=layout_progress,
            )
            item.stage = "workflow"
            item.save(update_fields=["stage"])
            workflow_operation = (
                "identifying_groups"
                if run.workflow.workflow_type == "unbundle_classify_extract"
                else (
                    "classifying"
                    if run.workflow.workflow_type.startswith("classify_")
                    else "extracting"
                )
            )
            progress_recorder.record(
                "analyzing", cast(ProgressOperation, workflow_operation), force=True
            )
            ctx = build_context(run, run_item=item, progress=progress_recorder.record)
            strategy = get_strategy(ctx.workflow_type)
            res = strategy.process_document(ctx, layout)
            item.stage = "persist"
            item.save(update_fields=["stage"])
            progress_recorder.record("saving_results", "saving_results", force=True)
            persist_result(run, doc, res, layout)
            item.duration_ms = int((time.perf_counter() - t0) * 1000)
            _append_run_warnings(
                run.pk,
                [f"{doc.original_filename}: {warning}" for warning in res.warnings],
            )
            if res.extraction_chunks and res.rejected_extraction_chunks == res.extraction_chunks:
                from docai.exceptions import InvalidModelOutput

                item.stage = "workflow"
                raise InvalidModelOutput(
                    "No extraction chunk returned a valid response. Check the workflow configuration and model output before retrying.",
                    retryable=False,
                )
            Document.objects.filter(pk=doc.pk).update(status=DOC_STATUS.processed)
            # The terminal item transition is last so another worker cannot
            # finalize the run while this task still has database work in flight.
            progress_recorder.record("complete", "complete", force=True)
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
            progress_recorder.record("complete", "cancelled", force=True)
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
                diagnostics=exception_context(exc),
                progress_recorder=progress_recorder,
            )
        except Exception as exc:  # noqa: BLE001
            _fail(
                item,
                "INTERNAL_ERROR",
                "Processing failed unexpectedly. Reference the trace id when reporting.",
                False,
                t0,
                queue_for_retry=False,
                diagnostics=exception_context(exc),
                progress_recorder=progress_recorder,
            )
        finally:
            with suppress(ValueError):
                reset_trace_id(token)
        return item.status


def _fail(
    item,
    code,
    message,
    retryable,
    t0,
    *,
    queue_for_retry=False,
    diagnostics=None,
    progress_recorder: ProgressRecorder,
):
    failed_stage = item.stage
    Document.objects.filter(pk=item.document_id).update(status=DOC_STATUS.failed)
    item.status = ITEM_STATUS.queued if queue_for_retry else ITEM_STATUS.failed
    if queue_for_retry:
        item.stage = "retry_wait"
    item.error_code, item.error_message, item.retryable = code, message[:2000], retryable
    item.duration_ms = int((time.perf_counter() - t0) * 1000)
    retry_phase = (
        "preparing_scans"
        if failed_stage == "normalization"
        else "reading_document"
        if failed_stage == "layout"
        else "analyzing"
    )
    progress_recorder.record(
        cast(ProgressPhase, retry_phase) if queue_for_retry else "complete",
        "retry_wait" if queue_for_retry else "failed",
        force=True,
    )
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
        **(diagnostics or {}),
        event="processing_failed",
        stage=failed_stage,
        error_code=code,
        retryable=retryable,
        retry_pending=queue_for_retry,
        duration_ms=item.duration_ms,
        reason=message,
    ).log("WARNING" if queue_for_retry else "ERROR", "Processing failed")


def _record_local_execution_interruption(run_id) -> int:
    """Make unfinished inline work visible and retryable after an executor failure."""
    now = timezone.now()
    message = "Local execution stopped before this document completed. It is safe to retry."
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run_id)
        interrupted_items = list(
            run.items.select_for_update().filter(
                status__in=(ITEM_STATUS.queued, ITEM_STATUS.running)
            )
        )
        for item in interrupted_items:
            item.status = ITEM_STATUS.failed
            item.stage = "execution_interrupted"
            item.error_code = "EXECUTION_INTERRUPTED"
            item.error_message = message
            item.retryable = True
            item.status_changed = now
            item.modified = now
            item.processing_progress = snapshot(
                "complete", "failed", now=now, previous=item.processing_progress
            )
            item.progress_updated_at = now
        RunItem.objects.bulk_update(
            interrupted_items,
            [
                "status",
                "stage",
                "error_code",
                "error_message",
                "retryable",
                "status_changed",
                "modified",
                "processing_progress",
                "progress_updated_at",
            ],
        )
        interrupted = len(interrupted_items)
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
    attempt: int
    task_id: str


def process_celery_delivery(item_id: str, *, task_id: str, retries: int) -> CeleryDelivery:
    """Process a Celery delivery and derive its retry decision from durable state."""
    policy = current_task_runtime_policy()
    retry_available = retries < policy.max_retries
    status = process_item(
        item_id,
        execution_id=task_id,
        retry_retryable=retry_available,
    )
    item = RunItem.objects.only(
        "run_id", "retryable", "error_code", "worker_task_id", "attempts"
    ).get(pk=item_id)
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
        attempt=item.attempts,
        task_id=task_id,
    )


def record_retry_schedule(item_id: str, *, attempt: int, task_id: str, retry_at: datetime) -> bool:
    """Record a retry only after Celery has calculated its real schedule."""
    try:
        with transaction.atomic():
            current = (
                RunItem.objects.filter(
                    pk=item_id,
                    attempts=attempt,
                    worker_task_id=task_id,
                    status=ITEM_STATUS.queued,
                )
                .values_list("processing_progress", flat=True)
                .first()
            )
    except Exception as exc:  # noqa: BLE001 -- retry telemetry is best effort
        logger.bind(
            event="progress_record_failed",
            item_id=item_id,
            error_type=type(exc).__name__,
        ).warning("Retry schedule milestone could not be read")
        return False
    if current is None:
        return False
    try:
        phase = ProcessingProgress.model_validate(current).phase
    except ValueError:
        phase = "analyzing"
    return ProgressRecorder(item_id, attempt, task_id).record(
        phase,
        "retry_wait",
        retry_at=retry_at,
        allowed_statuses=(ITEM_STATUS.queued,),
        force=True,
    )


def mark_retry_dispatch_failed(item_id: str, *, attempt: int, task_id: str) -> None:
    """Make a broker failure visible without letting a queued item stall forever."""
    ProgressRecorder(item_id, attempt, task_id).record(
        "complete",
        "failed",
        allowed_statuses=(ITEM_STATUS.queued,),
        force=True,
    )
    now = timezone.now()
    RunItem.objects.filter(
        pk=item_id,
        attempts=attempt,
        worker_task_id=task_id,
        status=ITEM_STATUS.queued,
    ).update(
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
    with transaction.atomic():
        stale = list(
            RunItem.objects.select_for_update().filter(
                Q(status=ITEM_STATUS.running)
                | Q(status=ITEM_STATUS.queued, stage="retry_wait")
                | Q(status=ITEM_STATUS.queued, stage=_LOCAL_QUEUED_STAGE),
                status_changed__lt=now - timedelta(seconds=age_seconds),
            )
        )
        run_ids = list(dict.fromkeys(item.run_id for item in stale))
        for item in stale:
            local_queue_lost = (
                item.status == ITEM_STATUS.queued and item.stage == _LOCAL_QUEUED_STAGE
            )
            item.status = ITEM_STATUS.failed
            item.stage = "local_queue_lost" if local_queue_lost else "worker_lost"
            item.error_code = "LOCAL_QUEUE_LOST" if local_queue_lost else "WORKER_LOST"
            item.error_message = (
                "The web process stopped before local processing began. It is safe to retry."
                if local_queue_lost
                else "The worker stopped before this item or its retry completed. It is safe to retry."
            )
            item.retryable = True
            item.status_changed = now
            item.modified = now
            item.processing_progress = snapshot(
                "complete", "failed", now=now, previous=item.processing_progress
            )
            item.progress_updated_at = now
        RunItem.objects.bulk_update(
            stale,
            [
                "status",
                "stage",
                "error_code",
                "error_message",
                "retryable",
                "status_changed",
                "modified",
                "processing_progress",
                "progress_updated_at",
            ],
        )
    recovered = len(stale)
    for run_id in run_ids:
        finalize_run(run_id, only_if_complete=True)
    return RecoveryResult(recovered_items=recovered, affected_runs=len(run_ids))


def _reserve_local_run(run_id: Any, *, only_failed: bool) -> Run:
    """Persist local acceptance before handing work to the process coordinator."""
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run_id)
        if only_failed and not run.items.filter(status=ITEM_STATUS.failed).exists():
            raise RunStateError("This run has no failed items to retry.")
        if run.status == RUN_STATUS.succeeded or (
            run.status == RUN_STATUS.cancelled and not only_failed
        ):
            raise RunStateError()
        if run.status == RUN_STATUS.running and run.stage != _DISPATCH_FAILED_STAGE:
            raise RunStateError("This run is already executing.")

        selected = (
            run.items.filter(status=ITEM_STATUS.failed)
            if only_failed
            else run.items.filter(status__in=(ITEM_STATUS.queued, ITEM_STATUS.failed))
        )
        items = list(selected.only("id", "processing_progress"))
        if not items:
            raise RunStateError("This run has no documents available to execute.")

        accepted_at = timezone.now()
        run.status = RUN_STATUS.running
        run.started_at = run.started_at or accepted_at
        run.stage = _LOCAL_QUEUED_STAGE
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
        for item in items:
            item.status = ITEM_STATUS.queued
            item.stage = _LOCAL_QUEUED_STAGE
            item.worker_task_id = ""
            item.worker_deliveries = 0
            item.status_changed = accepted_at
            item.modified = accepted_at
            item.processing_progress = snapshot("queued", "queued", now=accepted_at)
            item.progress_updated_at = accepted_at
        RunItem.objects.bulk_update(
            items,
            [
                "status",
                "stage",
                "worker_task_id",
                "worker_deliveries",
                "status_changed",
                "modified",
                "processing_progress",
                "progress_updated_at",
            ],
        )
        return run


def _record_dispatch_failure(run_id: Any, message: str) -> None:
    """Keep an accepted run retryable when its execution transport rejects it."""
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=run_id)
        if run.stage == "finalized":
            return
        run.stage = _DISPATCH_FAILED_STAGE
        if not run.errors or run.errors[-1] != message:
            run.errors = [*(run.errors or []), message][-200:]
        run.save(update_fields=["stage", "errors", "modified"])


def _queue_unavailable(run_id: Any, message: str, exc: Exception) -> IntegrationError:
    _record_dispatch_failure(run_id, message)
    logger.bind(run_id=str(run_id), error_type=type(exc).__name__).error("run dispatch failed")
    return IntegrationError(
        "Document processing could not be queued. Restore the execution service and retry.",
        error_code="EXECUTION_QUEUE_UNAVAILABLE",
        headers={"Retry-After": "2"},
    )


def schedule_run(run_id: Any, *, only_failed: bool = False) -> Run:
    """Accept HTTP-triggered work without running local processing in the request.

    Celery publication is already asynchronous and remains one task per document.
    Broker-free runners use a single process-local coordinator; callers that need
    deterministic completion should continue to call :func:`execute_run`.
    """
    policy = current_task_runtime_policy()
    if policy.runner == "celery":
        return execute_run(run_id, only_failed=only_failed)
    if policy.runner not in {"sync", "thread"}:
        _get_dispatcher(policy.runner)  # raise the established configuration error

    run = _reserve_local_run(run_id, only_failed=only_failed)
    try:
        _local_run_coordinator.submit(
            run.pk,
            only_failed=only_failed,
            runner=policy.runner,
        )
    except Exception as exc:
        message = (
            "The local execution coordinator could not accept this run. "
            "Retry after the web process is healthy."
        )
        raise _queue_unavailable(run.pk, message, exc) from exc
    return run


def execute_run(
    run_id,
    only_failed: bool = False,
    *,
    _scheduled_local: bool = False,
    _runner: str | None = None,
) -> Run:
    """Drive all items through the configured task runner, then finalize."""
    dispatcher = _get_dispatcher() if _runner is None else _get_dispatcher(_runner)
    with transaction.atomic():
        run = Run.objects.select_for_update().get(id=run_id)
        retry_status = ITEM_STATUS.queued if _scheduled_local else ITEM_STATUS.failed
        retry_filter = Q(status=retry_status)
        if _scheduled_local:
            retry_filter &= Q(stage=_LOCAL_QUEUED_STAGE)
        if only_failed and not run.items.filter(retry_filter).exists():
            raise RunStateError("This run has no failed items to retry.")
        if run.status == RUN_STATUS.succeeded or (
            run.status == RUN_STATUS.cancelled and not only_failed
        ):
            raise RunStateError()
        accepted_local = _scheduled_local and run.stage == _LOCAL_QUEUED_STAGE
        if (
            run.status == RUN_STATUS.running
            and run.stage != _DISPATCH_FAILED_STAGE
            and not accepted_local
        ):
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
        if _scheduled_local:
            qs = run.items.filter(status=ITEM_STATUS.queued, stage=_LOCAL_QUEUED_STAGE)
        else:
            qs = (
                run.items.filter(status=ITEM_STATUS.failed)
                if only_failed
                else run.items.filter(status__in=(ITEM_STATUS.queued, ITEM_STATUS.failed))
            )
        items = list(qs.only("id", "status", "processing_progress"))
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
                item.processing_progress = snapshot("queued", "queued", now=changed_at)
                item.progress_updated_at = changed_at
            RunItem.objects.bulk_update(
                items,
                [
                    "status",
                    "stage",
                    "worker_task_id",
                    "worker_deliveries",
                    "status_changed",
                    "modified",
                    "processing_progress",
                    "progress_updated_at",
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
            message = (
                "The worker queue could not accept every item. "
                "Retry execution after restoring the broker."
            )
            raise _queue_unavailable(run.pk, message, exc) from exc
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
    queued_items = list(run.items.select_for_update().filter(status=ITEM_STATUS.queued))
    for item in queued_items:
        item.status = ITEM_STATUS.skipped
        item.stage = "cancelled"
        item.error_code = item.error_message = ""
        item.retryable = False
        item.status_changed = now
        item.modified = now
        item.processing_progress = snapshot(
            "complete", "cancelled", now=now, previous=item.processing_progress
        )
        item.progress_updated_at = now
    RunItem.objects.bulk_update(
        queued_items,
        [
            "status",
            "stage",
            "error_code",
            "error_message",
            "retryable",
            "status_changed",
            "modified",
            "processing_progress",
            "progress_updated_at",
        ],
    )
    run.cancel_requested = True
    run.stage = "cancelling"
    run.updated_by = user
    run.save(update_fields=["cancel_requested", "stage", "updated_by", "modified"])
    audit.record(user, "run.cancel_requested", run)

    if not run.items.filter(status=ITEM_STATUS.running).exists():
        return finalize_run(run.pk)
    return run


def progress(run: Run) -> dict:
    """Return scalar aggregates plus a separate, bounded activity query."""
    items = run.items.all()
    aggregates = items.aggregate(
        total=Count("id"),
        succeeded=Count("id", filter=Q(status=ITEM_STATUS.succeeded)),
        failed=Count("id", filter=Q(status=ITEM_STATUS.failed)),
        skipped=Count("id", filter=Q(status=ITEM_STATUS.skipped)),
        queued=Count("id", filter=Q(status=ITEM_STATUS.queued)),
        running=Count("id", filter=Q(status=ITEM_STATUS.running)),
        retried=Count("id", filter=Q(attempts__gt=1)),
        retry_wait=Count("id", filter=Q(stage="retry_wait")),
        latest_success_at=Max("modified", filter=Q(status=ITEM_STATUS.succeeded)),
        last_milestone_at=Max("progress_updated_at"),
    )
    total = aggregates["total"] or 0
    succeeded = aggregates["succeeded"] or 0
    failed = aggregates["failed"] or 0
    skipped = aggregates["skipped"] or 0
    done = succeeded + failed + skipped
    remaining = total - done
    as_of = timezone.now()
    estimated_finish_at = None
    latest_success_at = aggregates["latest_success_at"]
    if (
        run.started_at
        and latest_success_at
        and succeeded >= 3
        and remaining > 0
        and not failed
        and not skipped
        and not aggregates["retried"]
        and not aggregates["retry_wait"]
        and not run.cancel_requested
        and run.status == RUN_STATUS.running
    ):
        elapsed_to_success = latest_success_at - run.started_at
        estimated_finish_at = latest_success_at + elapsed_to_success / succeeded * remaining
    estimated_seconds_remaining = (
        max(0, round((estimated_finish_at - as_of).total_seconds()))
        if estimated_finish_at
        else None
    )
    activity_items = list(
        items.filter(status__in=(ITEM_STATUS.running, ITEM_STATUS.queued))
        .select_related("document")
        .annotate(
            activity_priority=Case(
                When(status=ITEM_STATUS.running, then=0),
                When(stage="retry_wait", then=1),
                default=2,
                output_field=IntegerField(),
            )
        )
        .order_by("activity_priority", "created", "id")[:5]
    )
    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "queued": aggregates["queued"] or 0,
        "running": aggregates["running"] or 0,
        "remaining": remaining,
        "stage": run.stage,
        "estimated_seconds_remaining": estimated_seconds_remaining,
        "estimated_finish_at": estimated_finish_at,
        "as_of": as_of,
        "last_milestone_at": aggregates["last_milestone_at"],
        "activity_items": activity_items,
    }
