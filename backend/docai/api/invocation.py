"""Invoke a pinned workflow and retrieve JSON without using the frontend."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.cache import patch_cache_control, patch_vary_headers
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView

from docai.adapters.storage import file_digest
from docai.api.envelope import SuccessResponse
from docai.api.openapi import ErrorEnvelopeSerializer, InvocationAcceptedSerializer
from docai.api.permissions import OPERATOR, DocAIPermission
from docai.exceptions import Conflict, DocAIError, ValidationFailed
from docai.models import CONFIG_STATUS, Dataset, WorkflowConfiguration, WorkflowInvocation
from docai.models.results import INVOCATION_STATUS
from docai.services import ingestion, runs
from docai.services import run_execution as execution
from docai.services.headless_contracts import run_result_links

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._~:/+=-]+$")


class InvocationRequestSerializer(serializers.Serializer):
    dataset = serializers.UUIDField(help_text="Dataset in the workflow's project.")
    document_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=False,
        help_text="Existing documents to process. Supply this OR multipart files.",
    )
    files = serializers.ListField(
        child=serializers.FileField(),
        required=False,
        allow_empty=False,
        help_text="Upload documents using repeated multipart 'files' fields.",
    )
    name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    client_reference = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=120,
        help_text="Caller-owned reference returned on the run and available as a run filter.",
    )

    def validate(self, data):
        if bool(data.get("files")) == bool(data.get("document_ids")):
            raise serializers.ValidationError("Supply either files or document_ids, but not both.")
        count = len(data.get("files") or data.get("document_ids") or [])
        if count > settings.DOCAI["MAX_BATCH_FILES"]:
            raise serializers.ValidationError("Too many documents in one request.")
        return data


def _acceptance_response(invocation, request, *, replayed: bool = False):
    """Return the same bounded operation handle for acceptance and replay."""
    run = invocation.run
    if run is None:
        raise RuntimeError("an accepted invocation must have a run")
    links = run_result_links(run, request)
    results_url = str(links["results"])
    response = SuccessResponse(
        {
            "run_id": str(run.pk),
            "status": run.status,
            "client_reference": run.client_reference,
            "idempotency_expires_at": invocation.expires_at,
            "links": links,
        },
        status=202,
        message="Workflow invocation accepted",
        headers={"Location": results_url, "Retry-After": "2"},
    )
    if replayed:
        response["Idempotency-Replayed"] = "true"
    patch_cache_control(response, private=True, no_store=True)
    patch_vary_headers(response, ("Authorization", "Cookie"))
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _idempotency_key(request) -> str:
    key = str(request.headers.get("Idempotency-Key", "") or "").strip()
    if not key:
        raise ValidationFailed(
            "Supply an Idempotency-Key header.",
            error_code="IDEMPOTENCY_KEY_REQUIRED",
            errors={"Idempotency-Key": "This header is required."},
        )
    if len(key) > 128 or not _IDEMPOTENCY_KEY.fullmatch(key):
        raise ValidationFailed(
            "Supply a valid Idempotency-Key header.",
            error_code="IDEMPOTENCY_KEY_INVALID",
            errors={
                "Idempotency-Key": (
                    "Use 1-128 letters, numbers, or the characters . _ ~ : / + = -."
                )
            },
        )
    return key


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
                invocation.status == INVOCATION_STATUS.dispatching and run.status == "queued"
            )
            if invocation.status == INVOCATION_STATUS.dispatching and _lease_is_active(invocation):
                return _InvocationClaim(invocation, "replay")
            if requires_dispatch:
                token = _new_lease(invocation, INVOCATION_STATUS.dispatching)
                if token:
                    return _InvocationClaim(invocation, "dispatch", token)
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


def _resolve_claim(claim: _InvocationClaim, request):
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
        return _acceptance_response(invocation, request, replayed=True)
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


class WorkflowInvokeView(APIView):
    permission_classes = [DocAIPermission]
    write_role = OPERATOR
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(
        operation_id="headless_workflow_invoke",
        summary="Invoke an approved workflow asynchronously",
        tags=["Headless integration"],
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description=(
                    "Unique key for this logical invocation. Reuse it only when retrying the "
                    "same request."
                ),
            )
        ],
        request=InvocationRequestSerializer,
        responses={
            202: OpenApiResponse(
                response=InvocationAcceptedSerializer,
                description="Stable run operation handle. Poll the results link after Retry-After.",
            ),
            409: OpenApiResponse(
                response=ErrorEnvelopeSerializer,
                description="Idempotency key conflict or an invocation still being accepted.",
            ),
        },
        examples=[
            OpenApiExample(
                "Invoke existing documents",
                value={
                    "dataset": "11111111-1111-4111-8111-111111111111",
                    "document_ids": ["22222222-2222-4222-8222-222222222222"],
                    "name": "September W-2 batch",
                    "client_reference": "claims-batch-1042",
                },
                request_only=True,
            )
        ],
        description=(
            "Run this exact approved workflow version using document_ids or multipart files. "
            "A required Idempotency-Key makes transport retries safe for 30 days. The endpoint "
            "always returns HTTP 202 after successful acceptance or replay; poll the results link."
        ),
    )
    def post(self, request, workflow_id, **kwargs):
        key = _idempotency_key(request)
        workflow = get_object_or_404(WorkflowConfiguration, pk=workflow_id)
        self.check_object_permissions(request, workflow)
        serializer = InvocationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        dataset = get_object_or_404(
            Dataset.available_objects,
            pk=data["dataset"],
            project=workflow.project,
        )
        self.check_object_permissions(request, dataset)
        request_hash = _request_hash(data)
        claim = _claim_invocation(
            user=request.user,
            workflow=workflow,
            dataset=dataset,
            key=key,
            request_hash=request_hash,
        )
        if response := _resolve_claim(claim, request):
            return response
        invocation = claim.invocation

        if claim.action == "dispatch":
            _dispatch(claim)
            invocation.refresh_from_db()
            run = invocation.run
            if run is None:
                raise RuntimeError("a dispatched invocation must have a run")
            run.refresh_from_db()
            return _acceptance_response(invocation, request, replayed=True)

        document_ids = data.get("document_ids")
        try:
            if data.get("files"):
                document_ids, rejected = [], []
                for uploaded in data["files"]:
                    try:
                        result = ingestion.ingest_or_reuse_upload(
                            dataset, uploaded.name, uploaded, user=request.user
                        )
                        document_ids.append(result.document.pk)
                    except DocAIError as exc:
                        ingestion.record_rejection(
                            dataset, uploaded.name, uploaded, exc, user=request.user
                        )
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
                user=request.user,
                data=data,
                document_ids=document_ids,
            )
            if invocation is None:
                refreshed = WorkflowInvocation.objects.select_related("run__workflow").get(
                    pk=claim.invocation.pk
                )
                if refreshed.run_id:
                    return _acceptance_response(refreshed, request, replayed=True)
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
                DocAIError(
                    "An unexpected error occurred. Reference this trace id when reporting it."
                ),
            )
            raise
        dispatch_claim = _InvocationClaim(invocation, "dispatch", claim.lease_token)
        _dispatch(dispatch_claim)
        invocation.refresh_from_db()
        invocation.run.refresh_from_db()
        return _acceptance_response(invocation, request)
