"""Own invocation acceptance, replay, recovery and safe retention as one lifetime.

HTTP callers supply authorization at the original dataset relationship; the
lifetime never receives a request or constructs a response. Durable transitions
remain fenced by the claim token, with publication outside the attachment lock.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404
from django.utils import timezone

from docai.adapters.storage import file_digest
from docai.exceptions import Conflict, DocAIError, ValidationFailed
from docai.models import (
    CONFIG_STATUS,
    RUN_STATUS,
    Dataset,
    WorkflowConfiguration,
    WorkflowInvocation,
)
from docai.models.results import INVOCATION_STATUS
from docai.services import ingestion, runs
from docai.services import run_execution as execution


@dataclass(frozen=True)
class InvocationResult:
    invocation: WorkflowInvocation
    replayed: bool = False


def _request_hash(data) -> str:
    """Build a stable identity without loading uploaded documents into memory."""
    identity: dict[str, object] = {
        "dataset": str(data["dataset"]),
        "name": data.get("name", ""),
        "client_reference": data.get("client_reference", ""),
    }
    if document_ids := data.get("document_ids"):
        identity["documents"] = sorted(str(pk) for pk in document_ids)
    else:
        files = []
        for uploaded in data.get("files", []):
            digest, size = file_digest(uploaded)
            files.append({"name": uploaded.name, "sha256": digest, "size": size})
        identity["files"] = sorted(files, key=lambda item: (item["sha256"], item["name"]))
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class _InvocationClaim:
    invocation: WorkflowInvocation
    action: Literal["accept", "dispatch", "replay", "failed", "busy"]
    lease_token: str = ""
    recover_dispatch: bool = False


def _lease_deadline():
    return timezone.now() + timedelta(seconds=settings.DOCAI["INVOCATION_LEASE_SECONDS"])


def _lease_is_active(invocation: WorkflowInvocation) -> bool:
    return bool(invocation.lease_expires_at and invocation.lease_expires_at > timezone.now())


def _new_lease(invocation: WorkflowInvocation, status: str) -> str | None:
    token = uuid4().hex
    updated = WorkflowInvocation.objects.filter(
        pk=invocation.pk,
        status=invocation.status,
        lease_token=invocation.lease_token,
        lease_expires_at=invocation.lease_expires_at,
    ).update(
        status=status,
        lease_token=token,
        lease_expires_at=_lease_deadline(),
        modified=timezone.now(),
    )
    if not updated:
        return None
    invocation.status = status
    invocation.lease_token = token
    invocation.refresh_from_db(fields=["lease_expires_at"])
    return token


def _ensure_invocable(workflow: WorkflowConfiguration) -> None:
    if workflow.workflow_type == "evaluate":
        raise Conflict(
            "Evaluation workflows cannot be invoked through this processing endpoint.",
            error_code="WORKFLOW_NOT_INVOCABLE",
        )
    if workflow.status != CONFIG_STATUS.approved:
        raise Conflict(
            "Approve this workflow version before invoking it through the integration API.",
            error_code="WORKFLOW_NOT_APPROVED",
        )


def _claim_existing(*, user, workflow, key, request_hash) -> _InvocationClaim:
    with transaction.atomic():
        invocation = (
            WorkflowInvocation.objects.select_for_update()
            .select_related("run__workflow")
            .get(created_by=user, workflow=workflow, key=key)
        )
        if invocation.request_hash != request_hash:
            raise Conflict(
                "This Idempotency-Key was already used with different input.",
                error_code="IDEMPOTENCY_KEY_REUSED",
            )
        if invocation.status == INVOCATION_STATUS.failed:
            return _InvocationClaim(invocation, "failed")
        if invocation.run_id:
            run = invocation.run
            if run is None:
                raise RuntimeError("run_id must resolve to a run")
            requires_dispatch = run.stage == "dispatch_failed" or (
                invocation.status == INVOCATION_STATUS.dispatching
                and (
                    run.status == "queued"
                    or run.items.filter(status="queued", stage="queued").exists()
                )
            )
            if invocation.status == INVOCATION_STATUS.dispatching and _lease_is_active(invocation):
                return _InvocationClaim(invocation, "replay")
            if requires_dispatch:
                token = _new_lease(invocation, INVOCATION_STATUS.dispatching)
                if token:
                    return _InvocationClaim(invocation, "dispatch", token, recover_dispatch=True)
                invocation.refresh_from_db()
                return _InvocationClaim(invocation, "replay")
            invocation.status = INVOCATION_STATUS.accepted
            invocation.lease_token = ""
            invocation.lease_expires_at = None
            invocation.save(update_fields=["status", "lease_token", "lease_expires_at", "modified"])
            return _InvocationClaim(invocation, "replay")
        if _lease_is_active(invocation):
            return _InvocationClaim(invocation, "busy")
        token = _new_lease(invocation, INVOCATION_STATUS.accepting)
        if token:
            return _InvocationClaim(invocation, "accept", token)
        invocation.refresh_from_db()
        return _InvocationClaim(invocation, "replay" if invocation.run_id else "busy")


def _claim_invocation(*, user, workflow, dataset, key, request_hash) -> _InvocationClaim:
    """Claim a short acceptance lease while preserving the long replay record."""
    try:
        with transaction.atomic():
            existing = WorkflowInvocation.objects.filter(
                created_by=user, workflow=workflow, key=key
            ).exists()
            if existing:
                return _claim_existing(
                    user=user, workflow=workflow, key=key, request_hash=request_hash
                )
            _ensure_invocable(workflow)
            token = uuid4().hex
            invocation = WorkflowInvocation.objects.create(
                workflow=workflow,
                dataset=dataset,
                key=key,
                request_hash=request_hash,
                status=INVOCATION_STATUS.accepting,
                lease_token=token,
                lease_expires_at=_lease_deadline(),
                created_by=user,
                updated_by=user,
            )
            return _InvocationClaim(invocation, "accept", token)
    except IntegrityError:
        return _claim_existing(user=user, workflow=workflow, key=key, request_hash=request_hash)


def _resolve_claim(claim: _InvocationClaim) -> InvocationResult | None:
    invocation = claim.invocation
    if claim.action == "failed":
        raise DocAIError(
            invocation.failure_message,
            error_code=invocation.failure_code,
            status_code=invocation.failure_status,
            errors=invocation.failure_errors,
        )
    if claim.action == "busy":
        raise Conflict(
            "An invocation with this key is still accepting documents. Retry shortly.",
            error_code="INVOCATION_IN_PROGRESS",
            retryable=True,
            headers={"Retry-After": "2"},
        )
    if claim.action == "replay":
        return InvocationResult(invocation, replayed=True)
    return None


def _record_failure(invocation, lease_token: str, exc: DocAIError) -> None:
    WorkflowInvocation.objects.filter(
        pk=invocation.pk,
        status=INVOCATION_STATUS.accepting,
        lease_token=lease_token,
    ).update(
        status=INVOCATION_STATUS.failed,
        lease_token="",
        lease_expires_at=None,
        failure_status=exc.status_code,
        failure_code=exc.error_code,
        failure_message=exc.message,
        failure_errors=exc.errors,
        modified=timezone.now(),
    )


def _attach_run(invocation, lease_token: str, *, workflow, dataset, user, data, document_ids):
    """Create and attach a run only while the caller owns the acceptance lease."""
    with transaction.atomic():
        locked = WorkflowInvocation.objects.select_for_update().get(pk=invocation.pk)
        if locked.status != INVOCATION_STATUS.accepting or locked.lease_token != lease_token:
            return None
        run = runs.create_run(
            workflow.project,
            workflow,
            dataset,
            user,
            name=data.get("name", ""),
            client_reference=data.get("client_reference", ""),
            document_ids=document_ids,
        )
        locked.run = run
        locked.status = INVOCATION_STATUS.dispatching
        locked.lease_expires_at = _lease_deadline()
        locked.save(update_fields=["run", "status", "lease_expires_at", "modified"])
        return locked


def _dispatch(claim: _InvocationClaim) -> None:
    invocation = claim.invocation
    try:
        if claim.recover_dispatch:
            execution.resume_run_dispatch(invocation.run_id)
        else:
            execution.schedule_run(invocation.run_id)
    except Exception:
        WorkflowInvocation.objects.filter(
            pk=invocation.pk,
            status=INVOCATION_STATUS.dispatching,
            lease_token=claim.lease_token,
        ).update(lease_expires_at=timezone.now(), modified=timezone.now())
        raise
    WorkflowInvocation.objects.filter(
        pk=invocation.pk,
        status=INVOCATION_STATUS.dispatching,
        lease_token=claim.lease_token,
    ).update(
        status=INVOCATION_STATUS.accepted,
        lease_token="",
        lease_expires_at=None,
        modified=timezone.now(),
    )


def invoke_workflow(
    *,
    user,
    workflow: WorkflowConfiguration,
    key: str,
    data,
    authorize_dataset: Callable[[Dataset], None],
) -> InvocationResult:
    """Accept validated input or replay its existing outcome.

    The caller must authorize the workflow first. Dataset authorization is
    required before fingerprinting, replay or mutation, including when an exact
    retry refers to a retired dataset. The callback raises on denied access.
    """
    existing_invocation = (
        WorkflowInvocation.objects.select_related("dataset__project")
        .filter(created_by=user, workflow=workflow, key=key)
        .first()
    )
    if existing_invocation is not None:
        # Replay authorization is anchored to the original relationship, even
        # after the dataset is retired. The fingerprint below still rejects a
        # caller that changes the submitted dataset or any other input.
        dataset = existing_invocation.dataset
    else:
        dataset = get_object_or_404(
            Dataset.available_objects,
            pk=data["dataset"],
            project=workflow.project,
        )
    authorize_dataset(dataset)
    request_hash = _request_hash(data)
    claim = _claim_invocation(
        user=user,
        workflow=workflow,
        dataset=dataset,
        key=key,
        request_hash=request_hash,
    )
    if response := _resolve_claim(claim):
        return response
    invocation = claim.invocation

    if claim.action == "dispatch":
        _dispatch(claim)
        invocation.refresh_from_db()
        run = invocation.run
        if run is None:
            raise RuntimeError("a dispatched invocation must have a run")
        run.refresh_from_db()
        return InvocationResult(invocation, replayed=True)

    document_ids = data.get("document_ids")
    try:
        if data.get("files"):
            document_ids, rejected = [], []
            for uploaded in data["files"]:
                try:
                    result = ingestion.ingest_or_reuse_upload(
                        dataset, uploaded.name, uploaded, user=user
                    )
                    document_ids.append(result.document.pk)
                except DocAIError as exc:
                    ingestion.record_rejection(dataset, uploaded.name, uploaded, exc, user=user)
                    rejected.append(
                        {
                            "filename": uploaded.name,
                            "code": exc.error_code,
                            "message": exc.message,
                        }
                    )
            if rejected:
                raise ValidationFailed(
                    errors={
                        "files": rejected,
                        "accepted_document_ids": [str(pk) for pk in document_ids],
                    }
                )
        invocation = _attach_run(
            invocation,
            claim.lease_token,
            workflow=workflow,
            dataset=dataset,
            user=user,
            data=data,
            document_ids=document_ids,
        )
        if invocation is None:
            refreshed = WorkflowInvocation.objects.select_related("run__workflow").get(
                pk=claim.invocation.pk
            )
            if refreshed.run_id:
                return InvocationResult(refreshed, replayed=True)
            raise Conflict(
                "Another request is accepting this invocation. Retry shortly.",
                error_code="INVOCATION_IN_PROGRESS",
                retryable=True,
                headers={"Retry-After": "2"},
            )
    except DocAIError as exc:
        _record_failure(claim.invocation, claim.lease_token, exc)
        raise
    except Exception:
        # The first response is still handled and logged by the global exception
        # handler. Persist only its public response so the reservation cannot
        # remain in "accepting" forever and an identical retry stays deterministic.
        _record_failure(
            claim.invocation,
            claim.lease_token,
            DocAIError("An unexpected error occurred. Reference this trace id when reporting it."),
        )
        raise
    dispatch_claim = _InvocationClaim(invocation, "dispatch", claim.lease_token)
    _dispatch(dispatch_claim)
    invocation.refresh_from_db()
    invocation.run.refresh_from_db()
    return InvocationResult(invocation)


_TERMINAL_RUN_STATUSES = (
    RUN_STATUS.succeeded,
    RUN_STATUS.partial,
    RUN_STATUS.failed,
    RUN_STATUS.cancelled,
)


def expired_cleanup_queryset(*, now=None) -> QuerySet[WorkflowInvocation]:
    """Return expired reservations that cannot still acquire or execute work.

    The predicate uses dates, status strings, and foreign-key nullability only.
    Avoiding JSON lookups keeps cleanup behavior consistent on SQLite and Oracle.
    """
    cutoff = now or timezone.now()
    safe_outcome = Q(run__status__in=_TERMINAL_RUN_STATUSES) | Q(
        status=INVOCATION_STATUS.failed,
        run__isnull=True,
    )
    return WorkflowInvocation.objects.filter(expires_at__lte=cutoff).filter(safe_outcome)


def purge_expired_invocations(*, now=None) -> int:
    """Delete replay state only after its guarantee and operation have ended."""
    deleted, _ = expired_cleanup_queryset(now=now).delete()
    return deleted
