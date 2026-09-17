"""Durable provider recovery, guarded by the same run-item claim as final results.

No network call occurs while holding the claim lock. Hashes include actual inputs,
not merely indexes: a changed prompt, boundary, layout or configuration cannot
reuse incompatible output. Artifact contents remain behind private Django storage.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from django.core.files.storage import default_storage
from django.db import transaction
from loguru import logger
from pydantic import BaseModel

from docai.adapters.llm.base import LLMCall
from docai.adapters.storage import artifact_path, read_bytes, save_bytes
from docai.exceptions import DocAIError
from docai.models import (
    ARTIFACT_KIND,
    ITEM_STATUS,
    ProcessingArtifact,
    ProcessingCheckpoint,
    Run,
    RunItem,
)
from docai.schemas.llm import StructuredResult


class ClaimLost(DocAIError):
    """The worker may no longer publish; cancellation/newer attempt owns the state."""

    error_code = "WORKER_CLAIM_LOST"
    message = "This processing attempt no longer owns the run item."


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"Unsupported checkpoint identity type: {type(value).__name__}")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=_json_value
        ).encode()
    ).hexdigest()


@contextmanager
def active_claim(item: RunItem, *, allow_cancelled: bool = False) -> Iterator[None]:
    """Short publication transaction; scalar predicates work on SQLite and Oracle."""
    with transaction.atomic():
        run = Run.objects.select_for_update().get(pk=item.run_id)
        current = RunItem.objects.select_for_update().get(pk=item.pk)
        if (
            (run.cancel_requested and not allow_cancelled)
            or current.status != ITEM_STATUS.running
            or current.attempts != item.attempts
            or current.worker_task_id != item.worker_task_id
        ):
            raise ClaimLost
        yield


class Checkpoints:
    def __init__(self, item: RunItem, *, provider_identity: dict | None = None):
        self.item = item
        self.provider_identity = provider_identity or {}

    def check(self) -> None:
        # Observation needs no write lock or transaction. Publication still takes
        # active_claim's locks and rechecks ownership after any intervening work.
        if not RunItem.objects.filter(
            pk=self.item.pk,
            run__cancel_requested=False,
            status=ITEM_STATUS.running,
            attempts=self.item.attempts,
            worker_task_id=self.item.worker_task_id,
        ).exists():
            raise ClaimLost

    def read_operation(self, key: str) -> dict | None:
        self.check()
        row = ProcessingCheckpoint.objects.filter(
            run_item=self.item, kind="di_operation", fingerprint=key
        ).first()
        return row.metadata if row else None

    def save_operation(self, key: str, metadata: dict) -> None:
        with active_claim(self.item):
            ProcessingCheckpoint.objects.update_or_create(
                run_item=self.item,
                kind="di_operation",
                fingerprint=key,
                defaults={"metadata": metadata, "created_by_id": self.item.run.created_by_id},
            )

    def _key(self, call: LLMCall) -> str:
        # Checkpoint segmentation too: deterministic reuse preserves stable instances
        # before extraction chunk identity is considered on a resumed attempt.
        return fingerprint(
            {
                "version": 1,
                "provider": self.provider_identity,
                "source": self.item.document.sha256,
                "layout": str(self.item.layout_artifact_id or ""),
                "snapshot": self.item.run.config_snapshot,
                "call": {name: value for name, value in vars(call).items() if name != "schema"},
                "schema": call.schema.model_json_schema(),
            }
        )

    def discard(self, call: LLMCall) -> None:
        """Domain validation rejected a response after its schema was accepted.

        Retain the private artifact for diagnostics but revoke reuse eligibility.
        A stale attempt must not remove a newer worker's published checkpoint.
        """
        with active_claim(self.item):
            ProcessingCheckpoint.objects.filter(
                run_item=self.item, kind="llm_output", fingerprint=self._key(call)
            ).delete()

    def invoke(
        self, call: LLMCall, invoke: Callable[[LLMCall], StructuredResult]
    ) -> StructuredResult:
        self.check()
        key = self._key(call)
        row = (
            ProcessingCheckpoint.objects.filter(
                run_item=self.item, kind="llm_output", fingerprint=key
            )
            .select_related("artifact")
            .first()
        )
        if row and row.artifact:
            data = read_bytes(row.artifact.storage_path)
            if hashlib.sha256(data).hexdigest() != row.artifact.sha256:
                raise ValueError("Checkpoint artifact failed integrity validation")
            result = StructuredResult.model_validate_json(data)
            result.parsed = call.schema.model_validate(result.parsed)
            self.check()
            logger.bind(
                event="llm_checkpoint_reused",
                stage=call.stage,
                chunk_index=call.chunk_index,
                segment_index=call.segment_index,
            ).info("Completed model output reused")
            return result
        result = invoke(call)
        # Only schema-valid provider results become checkpoints; usage is recorded
        # by the adapter for every real call, never by this reuse path.
        result.parsed = call.schema.model_validate(result.parsed)
        data = result.model_dump_json().encode()
        self.check()
        path, digest = save_bytes(
            artifact_path(str(self.item.document_id), "checkpoint", f"{uuid4().hex}.json"), data
        )
        published = False
        try:
            with active_claim(self.item):
                artifact = ProcessingArtifact.objects.create(
                    document_id=self.item.document_id,
                    kind=ARTIFACT_KIND.raw_service,
                    stage="llm_checkpoint",
                    storage_path=path,
                    sha256=digest,
                    size_bytes=len(data),
                    parameters={"run_id": str(self.item.run_id), "fingerprint": key},
                    created_by_id=self.item.run.created_by_id,
                )
                ProcessingCheckpoint.objects.get_or_create(
                    run_item=self.item,
                    kind="llm_output",
                    fingerprint=key,
                    defaults={"artifact": artifact, "created_by_id": self.item.run.created_by_id},
                )
            published = True
        finally:
            if not published:
                default_storage.delete(path)
        return result
