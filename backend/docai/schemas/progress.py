"""Validated, bounded progress snapshots for one run item."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ProgressPhase = Literal[
    "queued",
    "preparing_scans",
    "reading_document",
    "analyzing",
    "saving_results",
    "complete",
]
ProgressOperation = Literal[
    "queued",
    "preparing_scans",
    "reading_document",
    "waiting_for_ocr",
    "reusing_layout",
    "identifying_groups",
    "classifying",
    "extracting",
    "checking_evidence",
    "saving_results",
    "retry_wait",
    "complete",
    "failed",
    "cancelled",
]


class ProgressCounter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed: int = Field(ge=0)
    total: int = Field(ge=0)
    unit: Literal["pages", "chunks"]

    @model_validator(mode="after")
    def completed_does_not_exceed_total(self):
        if self.completed > self.total:
            raise ValueError("completed cannot exceed total")
        return self


class ProgressSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current: int = Field(ge=1)
    total: int = Field(ge=1)

    @model_validator(mode="after")
    def current_does_not_exceed_total(self):
        if self.current > self.total:
            raise ValueError("current cannot exceed total")
        return self


class ProcessingProgress(BaseModel):
    """The latest milestone only; this is deliberately not an event history."""

    model_config = ConfigDict(extra="forbid")

    phase: ProgressPhase
    operation: ProgressOperation
    phase_started_at: datetime
    operation_started_at: datetime
    completed_phases: list[ProgressPhase] = Field(default_factory=list, max_length=6)
    counter: ProgressCounter | None = None
    segment: ProgressSegment | None = None
    retry_at: datetime | None = None

    @field_validator("phase_started_at", "operation_started_at", "retry_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime | None):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("progress timestamps must include a UTC offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def completed_phases_are_unique(self):
        if len(set(self.completed_phases)) != len(self.completed_phases):
            raise ValueError("completed_phases must be unique")
        return self
