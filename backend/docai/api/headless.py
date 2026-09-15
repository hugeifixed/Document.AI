"""Read-only contracts for applications and agents consuming DocAI runs."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.utils.http import parse_etags
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from docai.api.openapi import RunResultsManifestSerializer, WorkflowContractSerializer
from docai.api.permissions import DocAIPermission, can_view_content
from docai.exceptions import DocAIError
from docai.models import CONFIG_STATUS, Run, WorkflowConfiguration
from docai.services.headless_contracts import (
    representation_etag,
    run_results_manifest,
    workflow_contract,
)

_RUN_MANIFEST_EXAMPLE = {
    "success": True,
    "message": "Operation completed successfully",
    "data": {
        "run_id": "11111111-1111-4111-8111-111111111111",
        "client_reference": "claims-batch-1042",
        "status": "running",
        "completed": False,
        "stage": "analyzing",
        "cancel_requested": False,
        "created_at": "2026-09-15T14:00:00Z",
        "started_at": "2026-09-15T14:00:01Z",
        "finished_at": None,
        "workflow": {
            "id": "22222222-2222-4222-8222-222222222222",
            "name": "W-2 extraction",
            "version": 3,
            "config_hash": "sha256:example",
        },
        "counts": {
            "run_items": {
                "total": 5,
                "queued": 2,
                "running": 1,
                "succeeded": 2,
                "failed": 0,
                "skipped": 0,
            },
            "fields": 38,
            "classifications": 2,
            "segments": 2,
        },
        "review": {"total": 3, "fields": 3, "classifications": 0, "segments": 0},
        "warnings": {"count": 0, "truncated": False, "items": []},
        "errors": {"count": 0, "truncated": False, "items": []},
        "links": {
            "results": "https://docai.example/api/v1/runs/11111111-1111-4111-8111-111111111111/results/",
            "run": "https://docai.example/api/v1/runs/11111111-1111-4111-8111-111111111111/",
            "progress": "https://docai.example/api/v1/runs/11111111-1111-4111-8111-111111111111/progress/",
            "run_items": "https://docai.example/api/v1/run-items/?run=11111111-1111-4111-8111-111111111111",
            "fields": "https://docai.example/api/v1/fields/?run=11111111-1111-4111-8111-111111111111",
            "classifications": "https://docai.example/api/v1/classifications/?run=11111111-1111-4111-8111-111111111111",
            "segments": "https://docai.example/api/v1/segments/?run=11111111-1111-4111-8111-111111111111",
            "cancel": "https://docai.example/api/v1/runs/11111111-1111-4111-8111-111111111111/cancel/",
            "exports": {
                "json": "https://docai.example/api/v1/runs/11111111-1111-4111-8111-111111111111/export/json/",
                "csv": "https://docai.example/api/v1/runs/11111111-1111-4111-8111-111111111111/export/csv/",
                "xlsx": "https://docai.example/api/v1/runs/11111111-1111-4111-8111-111111111111/export/xlsx/",
            },
            "workflow_contract": "https://docai.example/api/v1/workflows/22222222-2222-4222-8222-222222222222/contract/",
        },
    },
    "trace_id": "abcd1234abcd1234",
}

_WORKFLOW_CONTRACT_EXAMPLE = {
    "success": True,
    "message": "Operation completed successfully",
    "data": {
        "id": "22222222-2222-4222-8222-222222222222",
        "project": "33333333-3333-4333-8333-333333333333",
        "name": "W-2 extraction",
        "version": 3,
        "workflow_type": "extract_structured",
        "config_hash": "sha256:example",
        "status": "approved",
        "input": {
            "formats": ["docx", "jpeg", "pdf", "png", "tiff", "txt", "xls", "xlsx"],
            "invocation_modes": ["document_ids", "multipart_files"],
            "max_batch_files": 20,
            "max_file_mb": 50,
            "max_pages": 500,
            "max_sheets": 100,
        },
        "output": {
            "resources": ["fields"],
            "categories": [],
            "schemas": [
                {
                    "name": "w2",
                    "version": 1,
                    "mode": "custom",
                    "fields": [
                        {
                            "name": "employee_name",
                            "description": "Employee name",
                            "type": "string",
                            "required": True,
                            "enum": [],
                        }
                    ],
                }
            ],
        },
        "links": {
            "workflow": "https://docai.example/api/v1/workflows/22222222-2222-4222-8222-222222222222/",
            "invoke": "https://docai.example/api/v1/workflows/22222222-2222-4222-8222-222222222222/invoke/",
        },
    },
    "trace_id": "abcd1234abcd1234",
}


def _private_conditional_response(response: Response, *, etag: str, pending: bool) -> Response:
    """Permit private revalidation while preventing reuse without validation."""
    patch_cache_control(response, private=True, no_cache=True, must_revalidate=True)
    patch_vary_headers(response, ("Authorization", "Cookie"))
    response["Pragma"] = "no-cache"
    response["ETag"] = etag
    response["X-Content-Type-Options"] = "nosniff"
    if pending:
        response["Retry-After"] = "2"
    return response


def _etag_matches(header: str, current: str) -> bool:
    """If-None-Match uses weak comparison for GET and HEAD requests."""
    requested = parse_etags(header)
    current_value = current.removeprefix("W/")
    return "*" in requested or any(tag.removeprefix("W/") == current_value for tag in requested)


class RunJSONResultsView(APIView):
    permission_classes = [DocAIPermission]

    @extend_schema(
        operation_id="headless_run_results_retrieve",
        summary="Retrieve a bounded run-result manifest",
        tags=["Headless integration"],
        parameters=[
            OpenApiParameter(
                "If-None-Match",
                str,
                OpenApiParameter.HEADER,
                required=False,
                description="ETag from an earlier poll; unchanged representations return 304.",
            )
        ],
        responses={
            200: OpenApiResponse(
                response=RunResultsManifestSerializer,
                description="Terminal run manifest.",
            ),
            202: OpenApiResponse(
                response=RunResultsManifestSerializer,
                description="Processing manifest. Honor Retry-After before polling again.",
            ),
            304: OpenApiResponse(response=None, description="The run manifest has not changed."),
        },
        examples=[
            OpenApiExample(
                "Run in progress",
                value=_RUN_MANIFEST_EXAMPLE,
                response_only=True,
                status_codes=["202"],
            )
        ],
        description=(
            "Returns bounded state and aggregate counts. Follow the supplied paginated links "
            "for individual results, or an export link for a complete delivery package."
        ),
    )
    def get(self, request, run_id, **kwargs):
        if not can_view_content(request.user):
            raise DocAIError(
                "Your role cannot read extracted document content.",
                error_code="PERMISSION_DENIED",
                status_code=403,
            )
        run = get_object_or_404(Run.objects.select_related("workflow"), pk=run_id)
        self.check_object_permissions(request, run)
        manifest = run_results_manifest(run, request)
        etag = representation_etag(manifest)
        pending = not bool(manifest["completed"])
        if _etag_matches(request.headers.get("If-None-Match", ""), etag):
            return _private_conditional_response(Response(status=304), etag=etag, pending=pending)
        response = Response(
            manifest,
            status=202 if pending else 200,
            headers={"Location": manifest["links"]["results"]},  # type: ignore[index]
        )
        return _private_conditional_response(response, etag=etag, pending=pending)


class WorkflowContractView(APIView):
    permission_classes = [DocAIPermission]

    @extend_schema(
        operation_id="headless_workflow_contract_retrieve",
        summary="Retrieve an approved workflow contract",
        tags=["Headless integration"],
        responses={200: WorkflowContractSerializer},
        examples=[
            OpenApiExample(
                "Structured extraction contract",
                value=_WORKFLOW_CONTRACT_EXAMPLE,
                response_only=True,
                status_codes=["200"],
            )
        ],
        description=(
            "Describes accepted inputs and output resources for an approved workflow version. "
            "Prompt content, credentials, model deployment details, and provider settings are excluded."
        ),
    )
    def get(self, request, workflow_id, **kwargs):
        workflow = get_object_or_404(
            WorkflowConfiguration.objects.select_related("project"),
            pk=workflow_id,
            status=CONFIG_STATUS.approved,
        )
        self.check_object_permissions(request, workflow)
        return Response(workflow_contract(workflow, request))
