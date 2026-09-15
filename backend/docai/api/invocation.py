"""Invoke a pinned workflow and retrieve JSON without using the frontend."""

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_cache_control
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import serializers
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from docai.api.permissions import OPERATOR, DocAIPermission, can_view_content
from docai.exceptions import DocAIError, ValidationFailed
from docai.models import Dataset, Run, WorkflowConfiguration
from docai.services import export, ingestion, runs
from docai.services import run_execution as execution


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
    name = serializers.CharField(required=False, allow_blank=True, max_length=160)

    def validate(self, data):
        if bool(data.get("files")) == bool(data.get("document_ids")):
            raise serializers.ValidationError("Supply either files or document_ids, but not both.")
        count = len(data.get("files") or data.get("document_ids") or [])
        if count > settings.DOCAI["MAX_BATCH_FILES"]:
            raise serializers.ValidationError("Too many documents in one request.")
        return data


def results_response(run, request):
    completed = run.status in {"succeeded", "partial", "failed", "cancelled"}
    url = reverse("run-json-results", kwargs={"run_id": run.pk}, request=request)
    result = None
    if completed:
        package = export.run_package(run)
        result = {key: package[key] for key in ("fields", "classifications", "segments", "errors")}
    response = Response(
        {
            "run_id": str(run.pk),
            "status": run.status,
            "completed": completed,
            "workflow": {
                "id": str(run.workflow_id),
                "name": run.workflow.name,
                "version": run.workflow.version,
                "config_hash": run.config_hash,
            },
            "results_url": url,
            "results": result,
            "errors": run.errors,
        },
        status=200 if completed else 202,
        headers={"Location": url},
    )
    if not completed:
        response["Retry-After"] = "2"
    patch_cache_control(response, private=True, no_store=True)
    response["X-Content-Type-Options"] = "nosniff"
    return response


class WorkflowInvokeView(APIView):
    permission_classes = [DocAIPermission]
    write_role = OPERATOR
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(
        request=InvocationRequestSerializer,
        responses={200: OpenApiTypes.OBJECT, 202: OpenApiTypes.OBJECT},
        description=(
            "Run this exact workflow version using document_ids or multipart files. "
            "Returns JSON results when execution finishes inline, or HTTP 202 with results_url "
            "for background execution. Inspect status and results.errors even on HTTP 200."
        ),
    )
    def post(self, request, workflow_id, **kwargs):
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
        document_ids = data.get("document_ids")
        if data.get("files"):
            document_ids, rejected = [], []
            for uploaded in data["files"]:
                try:
                    doc = ingestion.ingest_upload(
                        dataset, uploaded.name, uploaded, user=request.user
                    )
                    document_ids.append(doc.pk)
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
        run = runs.create_run(
            workflow.project,
            workflow,
            dataset,
            request.user,
            name=data.get("name", ""),
            document_ids=document_ids,
        )
        run = execution.execute_run(run.pk)
        return results_response(run, request)


class RunJSONResultsView(APIView):
    permission_classes = [DocAIPermission]

    @extend_schema(responses={200: OpenApiTypes.OBJECT, 202: OpenApiTypes.OBJECT})
    def get(self, request, run_id, **kwargs):
        if not can_view_content(request.user):
            raise DocAIError(
                "Your role cannot read extracted document content.",
                error_code="PERMISSION_DENIED",
                status_code=403,
            )
        run = get_object_or_404(Run.objects.select_related("workflow"), pk=run_id)
        self.check_object_permissions(request, run)
        return results_response(run, request)
