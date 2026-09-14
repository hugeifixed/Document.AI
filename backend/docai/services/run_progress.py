"""Best-effort persistence for bounded run-item progress snapshots."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, cast

from django.db import transaction
from django.utils import timezone
from loguru import logger
from pydantic import ValidationError

from docai.models import ITEM_STATUS, RunItem
from docai.schemas.progress import (
    ProcessingProgress,
    ProgressCounter,
    ProgressOperation,
    ProgressPhase,
    ProgressSegment,
)

TERMINAL_OPERATIONS = {"complete", "failed", "cancelled"}


def snapshot(
    phase: ProgressPhase,
    operation: ProgressOperation,
    *,
    now: datetime | None = None,
    previous: dict[str, Any] | None = None,
    counter: ProgressCounter | dict[str, Any] | None = None,
    segment: ProgressSegment | dict[str, Any] | None = None,
    retry_at: datetime | None = None,
) -> dict[str, Any]:
    """Build one validated JSON-ready snapshot, tolerating old invalid JSON."""
    at = now or timezone.now()
    old: ProcessingProgress | None = None
    if previous:
        try:
            old = ProcessingProgress.model_validate(previous)
        except ValidationError:
            old = None
    completed = list(old.completed_phases) if old else []
    if old and old.phase != phase and old.phase not in completed:
        completed.append(old.phase)
    counter_value = ProgressCounter.model_validate(counter) if counter is not None else None
    segment_value = ProgressSegment.model_validate(segment) if segment is not None else None
    value = ProcessingProgress(
        phase=phase,
        operation=operation,
        phase_started_at=old.phase_started_at if old and old.phase == phase else at,
        operation_started_at=(
            old.operation_started_at if old and old.operation == operation else at
        ),
        completed_phases=completed[-6:],
        counter=counter_value,
        segment=segment_value,
        retry_at=retry_at,
    )
    return value.model_dump(mode="json")


@dataclass(slots=True)
class ProgressRecorder:
    """Update one claimed item while rejecting stale delivery callbacks."""

    item_id: Any
    attempt: int
    worker_task_id: str = ""
    throttle_seconds: float = 3.0
    _last_write: float = field(default=0.0, init=False, repr=False)
    _last_phase: str = field(default="", init=False, repr=False)
    _last_operation: str = field(default="", init=False, repr=False)
    _last_segment: tuple[int, int] | None = field(default=None, init=False, repr=False)

    def record(
        self,
        phase: ProgressPhase,
        operation: ProgressOperation,
        *,
        completed: int | None = None,
        total: int | None = None,
        unit: str | None = None,
        segment_current: int | None = None,
        segment_total: int | None = None,
        retry_at: datetime | None = None,
        allowed_statuses: Iterable[str] = (ITEM_STATUS.running,),
        force: bool = False,
    ) -> bool:
        now_monotonic = time.monotonic()
        next_segment = (
            (segment_current, segment_total)
            if segment_current is not None and segment_total is not None
            else None
        )
        transition = (
            phase != self._last_phase
            or operation != self._last_operation
            or next_segment != self._last_segment
        )
        if (
            not force
            and not transition
            and operation not in TERMINAL_OPERATIONS
            and now_monotonic - self._last_write < self.throttle_seconds
        ):
            return False
        try:
            counter = None
            if completed is not None or total is not None or unit is not None:
                if completed is None or total is None or unit not in ("pages", "chunks"):
                    raise ValueError("counter requires completed, total, and a supported unit")
                counter = ProgressCounter(
                    completed=completed,
                    total=total,
                    unit=cast(Literal["pages", "chunks"], unit),
                )
            segment = None
            if segment_current is not None or segment_total is not None:
                if segment_current is None or segment_total is None:
                    raise ValueError("segment requires current and total")
                segment = ProgressSegment(current=segment_current, total=segment_total)
            now = timezone.now()
            with transaction.atomic():
                filters: dict[str, Any] = {
                    "pk": self.item_id,
                    "attempts": self.attempt,
                    "status__in": tuple(allowed_statuses),
                }
                if self.worker_task_id:
                    filters["worker_task_id"] = self.worker_task_id
                current = (
                    RunItem.objects.filter(**filters).values("processing_progress", "stage").first()
                )
                if current is None:
                    return False
                value = snapshot(
                    phase,
                    operation,
                    now=now,
                    previous=current["processing_progress"],
                    counter=counter,
                    segment=segment,
                    retry_at=retry_at,
                )
                updates: dict[str, Any] = {
                    "processing_progress": value,
                    "progress_updated_at": now,
                }
                if operation == "retry_wait" and retry_at is not None:
                    updates["stage"] = "retry_wait"
                elif current["stage"] == "retry_wait" and operation != "retry_wait":
                    updates["stage"] = {
                        "preparing_scans": "normalization",
                        "reading_document": "layout",
                        "analyzing": "workflow",
                        "saving_results": "persist",
                        "complete": "done",
                    }[phase]
                updated = RunItem.objects.filter(**filters).update(**updates)
            if updated:
                self._last_write = now_monotonic
                self._last_phase = phase
                self._last_operation = operation
                self._last_segment = next_segment
            return bool(updated)
        except Exception as exc:  # noqa: BLE001 -- telemetry cannot abort document work
            logger.bind(
                event="progress_record_failed",
                item_id=str(self.item_id),
                error_type=type(exc).__name__,
            ).warning("Progress milestone could not be recorded")
            return False
