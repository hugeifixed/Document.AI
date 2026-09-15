"""Invoke a pinned workflow and retrieve JSON without using the frontend."""

import re

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_cache_control, patch_vary_headers
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView

from docai.api.envelope import SuccessResponse
from docai.api.openapi import ErrorEnvelopeSerializer, InvocationAcceptedSerializer
from docai.api.permissions import OPERATOR, DocAIPermission
from docai.exceptions import ValidationFailed
from docai.models import WorkflowConfiguration
from docai.services import invocations
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
        result = invocations.invoke_workflow(
            user=request.user,
            workflow=workflow,
            key=key,
            data=serializer.validated_data,
            authorize_dataset=lambda dataset: self.check_object_permissions(request, dataset),
        )
        return _acceptance_response(result.invocation, request, replayed=result.replayed)
