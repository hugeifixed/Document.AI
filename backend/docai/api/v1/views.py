"""v1 viewsets. Views validate (serializers), authorize (permissions), and
delegate to services. No business logic, no adapters, no vendor SDKs here."""

from __future__ import annotations

from django.conf import settings
from django.db.models import Count
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_cache_control
from django.utils.http import content_disposition_header
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    extend_schema,
)
from pydantic import ValidationError as PydanticValidationError
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from docai.adapters.storage import open_file
from docai.api.envelope import SuccessResponse
from docai.api.filters import (
    ClassificationFilter,
    DocumentFilter,
    FieldFilter,
    LabelFilter,
    RunFilter,
    RunItemFilter,
    SegmentFilter,
    WorkflowFilter,
)
from docai.api.openapi import (
    BulkReviewResultSerializer,
    DatasetUploadRequestSerializer,
    DatasetUploadResultSerializer,
    EvaluationCreateRequestSerializer,
    LayoutBuildResultSerializer,
    ReasonRequestSerializer,
    ReclassifyRequestSerializer,
    ReviewHistoryEntrySerializer,
    RunProgressSerializer,
    SegmentMergeRequestSerializer,
    SegmentSplitRequestSerializer,
    UserProfileSerializer,
    WorkflowValidationRequestSerializer,
    WorkflowValidationResultSerializer,
)
from docai.api.permissions import APPROVER, OPERATOR, REVIEWER, DocAIPermission, can_view_content
from docai.exceptions import DocAIError, NotFound, ValidationFailed
from docai.models import (
    AuditEvent,
    CategoryDefinition,
    Dataset,
    Document,
    ExtractionTemplate,
    ModelConfiguration,
    Project,
    PromptVersion,
    Run,
    SchemaVersion,
    Segment,
    WorkflowConfiguration,
)
from docai.repositories import queries as q
from docai.schemas.config import CONFIG_SCHEMAS, validate_workflow_config
from docai.serializers.core import (
    AuditEventSerializer,
    BulkFieldReviewSerializer,
    CategoryRevisionSerializer,
    CategorySerializer,
    ClassificationSerializer,
    DatasetSerializer,
    DocumentDetailSerializer,
    DocumentSerializer,
    EvaluationSerializer,
    FieldReviewSerializer,
    FieldSerializer,
    LabelCreateSerializer,
    LabelSerializer,
    ModelConfigurationSerializer,
    ProjectSerializer,
    PromptVersionSerializer,
    ReviewActionSerializer,
    RunCreateSerializer,
    RunDetailSerializer,
    RunItemSerializer,
    RunSerializer,
    SchemaVersionSerializer,
    SegmentSerializer,
    TemplateSerializer,
    WorkflowSerializer,
)
from docai.services import dashboard as dashboard_svc
from docai.services import evaluation as eval_svc
from docai.services import export as export_svc
from docai.services import governance, ingestion, labeling, review
from docai.services import layouts as layout_svc
from docai.services import runs as run_svc


def _require_content_access(user):
    if not can_view_content(user):
        raise DocAIError(
            "Document content is available to operators, reviewers, and approvers only.",
            error_code="PERMISSION_DENIED",
            status_code=403,
        )


def _private_response(response):
    patch_cache_control(response, private=True, no_store=True)
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _location(request, basename: str, instance) -> str:
    return reverse(
        f"{basename}-detail",
        kwargs={"pk": instance.pk},
        request=request,
    )


def _created(request, basename: str, instance, serializer, *, message: str | None = None):
    data = serializer(instance, context={"request": request}).data
    headers = {"Location": _location(request, basename, instance)}
    if message:
        return SuccessResponse(
            data, status=status.HTTP_201_CREATED, headers=headers, message=message
        )
    return Response(data, status=status.HTTP_201_CREATED, headers=headers)


class _Base(viewsets.ModelViewSet):
    permission_classes = [DocAIPermission]
    write_role = OPERATOR

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return _created(request, self.basename, serializer.instance, self.get_serializer_class())


class ProjectViewSet(_Base):
    serializer_class = ProjectSerializer
    queryset = q.projects()
    search_fields = ["name", "slug", "description"]
    ordering_fields = ["name", "created", "modified"]
    ordering = ["name"]


class DatasetViewSet(_Base):
    serializer_class = DatasetSerializer
    queryset = q.datasets().annotate(document_count=Count("documents"))
    filterset_fields = ["project", "split", "is_production"]
    search_fields = ["name", "description"]
    ordering_fields = ["name", "created", "document_count"]
    ordering = ["name"]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(
        request=DatasetUploadRequestSerializer,
        responses={
            201: DatasetUploadResultSerializer,
            422: OpenApiResponse(
                DatasetUploadResultSerializer,
                description="No files were accepted; rejection details are returned for every file.",
            ),
        },
    )
    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def upload(self, request, pk=None, **kwargs):
        """Multipart upload of one or many files. Each file is validated before
        storage; rejected files are reported inline, never silently dropped."""
        dataset = self.get_object()
        files = request.FILES.getlist("files") or request.FILES.getlist("file")
        if not files:
            raise ValidationFailed(
                errors={"files": "Attach one or more files under the 'files' field."}
            )
        if len(files) > settings.DOCAI["MAX_BATCH_FILES"]:
            raise ValidationFailed(
                errors={"files": f"At most {settings.DOCAI['MAX_BATCH_FILES']} files per batch."}
            )
        accepted, rejected = [], []
        for f in files:
            try:
                doc = ingestion.ingest_upload(dataset, f.name, f, user=request.user)
                accepted.append(DocumentSerializer(doc, context={"request": request}).data)
            except DocAIError as exc:
                ingestion.record_rejection(dataset, f.name, f, exc, user=request.user)
                rejected.append(
                    {
                        "filename": f.name,
                        "error_code": exc.error_code,
                        "message": exc.message,
                        "errors": exc.errors,
                    }
                )
        return SuccessResponse(
            {"accepted": accepted, "rejected": rejected},
            status=status.HTTP_201_CREATED if accepted else status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=f"{len(accepted)} file(s) accepted, {len(rejected)} rejected",
            headers={"Location": reverse("document-list", request=request)} if accepted else None,
        )


class DocumentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [DocAIPermission]
    queryset = q.documents()
    filterset_class = DocumentFilter
    search_fields = ["original_filename", "sha256", "units__text_preview"]
    ordering_fields = [
        "original_filename",
        "created",
        "modified",
        "size_bytes",
        "page_count",
        "status",
    ]
    ordering = ["-created"]

    def get_serializer_class(self):
        return DocumentDetailSerializer if self.action == "retrieve" else DocumentSerializer

    @extend_schema(
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY},
        description=(
            "Streams the immutable source file using its stored MIME type and an inline content disposition. "
            "Document content is available to operators, reviewers, and approvers."
        ),
    )
    @action(detail=True, methods=["get"])
    def original(self, request, pk=None, **kwargs):
        """Stream the original file to users with document-content access."""
        doc = self.get_object()
        _require_content_access(request.user)
        resp = FileResponse(
            open_file(doc.storage_path),
            content_type=doc.mime_type or "application/octet-stream",
            as_attachment=False,
            filename=doc.original_filename,
        )
        resp["Content-Security-Policy"] = "sandbox"
        return _private_response(resp)

    @extend_schema(request=None, responses=LayoutBuildResultSerializer)
    @action(detail=True, methods=["post"])
    def layout(self, request, pk=None, **kwargs):
        """Build (or load) the normalized layout artifact now."""
        doc = self.get_object()
        layout = layout_svc.get_or_build_layout(doc)
        return Response(
            {
                "service": layout.service,
                "service_version": layout.service_version,
                "units": len(layout.units),
                "warnings": layout.warnings,
            }
        )

    @extend_schema(responses=OpenApiTypes.OBJECT)
    @action(detail=True, methods=["get"], url_path=r"units/(?P<index>\d+)")
    def unit(self, request, pk=None, index=None, **kwargs):
        """Normalized layout for one page/sheet: words, lines, tables, cells (for overlays and labeling)."""
        doc = self.get_object()
        _require_content_access(request.user)
        data = layout_svc.unit_layout(doc, int(index))
        if data is None:
            raise NotFound("No layout for that unit. Build the layout first.")
        return Response(data)


class CategoryViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [DocAIPermission]
    serializer_class = CategorySerializer
    queryset = CategoryDefinition.objects.select_related("project")
    filterset_fields = ["project", "key"]
    search_fields = ["key", "name", "description", "aliases"]
    ordering = ["key", "-version"]

    def create(self, request, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        category = governance.create_category_version(
            data.pop("project"), data.pop("key"), user=request.user, **data
        )
        return _created(request, self.basename, category, self.get_serializer_class())

    @extend_schema(request=CategoryRevisionSerializer, responses={201: CategorySerializer})
    @action(detail=True, methods=["post"])
    def revisions(self, request, pk=None, **kwargs):
        current = self.get_object()
        serializer = CategoryRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = governance.create_category_version(
            current.project,
            current.key,
            user=request.user,
            previous=current,
            **serializer.validated_data,
        )
        return _created(request, self.basename, category, self.get_serializer_class())


class SchemaVersionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [DocAIPermission]
    serializer_class = SchemaVersionSerializer
    queryset = SchemaVersion.objects.all()
    filterset_fields = ["name"]
    search_fields = ["name"]
    ordering = ["name", "-version"]

    def create(self, request, **kwargs):
        name = request.data.get("name")
        fields = request.data.get("field_definitions")
        if not name or not isinstance(fields, list):
            raise ValidationFailed(
                errors={"name": "required", "field_definitions": "list of field specs required"}
            )
        try:
            sv = governance.new_schema_version(name, fields, request.user)
        except PydanticValidationError as exc:
            raise ValidationFailed(errors={"field_definitions": str(exc)[:600]}) from None
        return _created(request, self.basename, sv, self.get_serializer_class())


class PromptVersionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [DocAIPermission]
    serializer_class = PromptVersionSerializer
    queryset = PromptVersion.objects.all()
    filterset_fields = ["name", "purpose"]
    search_fields = ["name", "system_prompt"]
    ordering = ["name", "-version"]

    def create(self, request, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        pv = governance.new_prompt_version(
            d["name"], d["purpose"], d["system_prompt"], d["user_template"], request.user
        )
        return _created(request, self.basename, pv, self.get_serializer_class())


class ModelConfigurationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [DocAIPermission]
    serializer_class = ModelConfigurationSerializer
    queryset = ModelConfiguration.objects.all()
    filterset_fields = ["name", "adapter", "deployment"]
    ordering = ["name", "-version"]

    def perform_create(self, serializer):
        last = (
            ModelConfiguration.objects.filter(name=serializer.validated_data["name"])
            .order_by("-version")
            .first()
        )
        serializer.save(
            version=(last.version + 1 if last else 1),
            created_by=self.request.user,
            updated_by=self.request.user,
        )

    def create(self, request, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return _created(request, self.basename, serializer.instance, self.get_serializer_class())


class TemplateViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [DocAIPermission]
    action_roles = {"approve": APPROVER}
    serializer_class = TemplateSerializer
    queryset = q.templates()
    filterset_fields = ["project", "document_type", "status", "name"]
    search_fields = ["name", "document_type"]
    ordering = ["name", "-version"]

    def perform_create(self, serializer):
        last = (
            ExtractionTemplate.objects.filter(
                project=serializer.validated_data["project"], name=serializer.validated_data["name"]
            )
            .order_by("-version")
            .first()
        )
        serializer.save(
            version=(last.version + 1 if last else 1),
            created_by=self.request.user,
            updated_by=self.request.user,
        )

    def create(self, request, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return _created(request, self.basename, serializer.instance, self.get_serializer_class())

    @extend_schema(request=ReasonRequestSerializer, responses=TemplateSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None, **kwargs):
        serializer = ReasonRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tpl = governance.approve_template(
            self.get_object(), request.user, serializer.validated_data.get("reason", "")
        )
        return Response(self.get_serializer(tpl).data)


class WorkflowViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [DocAIPermission]
    action_roles = {"approve": APPROVER, "retire": APPROVER}
    serializer_class = WorkflowSerializer
    queryset = q.workflows()
    filterset_class = WorkflowFilter
    search_fields = ["name", "workflow_type"]
    ordering_fields = ["name", "version", "created", "status"]
    ordering = ["name", "-version"]

    def create(self, request, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        wf = governance.create_workflow_version(
            d["project"], d["name"], d["workflow_type"], d["config"], request.user
        )
        return _created(request, self.basename, wf, self.get_serializer_class())

    @extend_schema(
        request=WorkflowValidationRequestSerializer,
        responses=WorkflowValidationResultSerializer,
    )
    @action(detail=False, methods=["post"])
    def validate(self, request, **kwargs):
        """Dry-run validation of a config (used by the workflow builder)."""
        serializer = WorkflowValidationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wt = serializer.validated_data["workflow_type"]
        cfg = serializer.validated_data["config"]
        try:
            validated = validate_workflow_config(wt, cfg)
        except ValueError as exc:
            raise ValidationFailed(errors={"config": str(exc)[:800]}) from None
        return Response(
            {"valid": True, "config": validated, "content_hash": governance.content_hash(validated)}
        )

    @extend_schema(responses=OpenApiTypes.OBJECT)
    @action(detail=False, methods=["get"])
    def types(self, request, **kwargs):
        """Workflow types + their JSON config schemas (drives the dynamic builder UI)."""
        from docai.models import WORKFLOW_TYPES

        return Response(
            {
                k: {
                    "label": str(WORKFLOW_TYPES[k]),
                    "schema": CONFIG_SCHEMAS[k].model_json_schema(),
                }
                for k in CONFIG_SCHEMAS
            }
        )

    @extend_schema(request=ReasonRequestSerializer, responses=WorkflowSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None, **kwargs):
        serializer = ReasonRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wf = governance.approve_workflow(
            self.get_object(), request.user, serializer.validated_data.get("reason", "")
        )
        return Response(self.get_serializer(wf).data)

    @extend_schema(request=ReasonRequestSerializer, responses=WorkflowSerializer)
    @action(detail=True, methods=["post"])
    def retire(self, request, pk=None, **kwargs):
        serializer = ReasonRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wf = governance.retire_workflow(
            self.get_object(), request.user, serializer.validated_data.get("reason", "")
        )
        return Response(self.get_serializer(wf).data)


class RunViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [DocAIPermission]
    queryset = q.runs()
    filterset_class = RunFilter
    search_fields = ["name", "workflow__name", "dataset__name", "config_hash"]
    ordering_fields = ["created", "started_at", "finished_at", "status", "total_items", "name"]
    ordering = ["-created"]

    def get_serializer_class(self):
        return RunDetailSerializer if self.action == "retrieve" else RunSerializer

    @extend_schema(
        request=RunCreateSerializer,
        responses={201: RunDetailSerializer, 202: RunDetailSerializer},
    )
    def create(self, request, **kwargs):
        s = RunCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        project = get_object_or_404(Project, pk=d["project"])
        workflow = get_object_or_404(WorkflowConfiguration, pk=d["workflow"], project=project)
        dataset = get_object_or_404(Dataset, pk=d["dataset"], project=project)
        run = run_svc.create_run(
            project,
            workflow,
            dataset,
            request.user,
            name=d.get("name", ""),
            sample_size=d.get("sample_size"),
            document_ids=d.get("document_ids"),
        )
        if d.get("execute", True):
            run = run_svc.execute_run(run.id)
        code = status.HTTP_202_ACCEPTED if run.status == "running" else status.HTTP_201_CREATED
        return SuccessResponse(
            RunDetailSerializer(run, context={"request": request}).data,
            status=code,
            message=f"Run {run.status}",
            headers={"Location": _location(request, self.basename, run)},
        )

    @extend_schema(
        request=None,
        responses={200: RunDetailSerializer, 202: RunDetailSerializer},
    )
    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None, **kwargs):
        run = run_svc.execute_run(self.get_object().id)
        return Response(
            RunDetailSerializer(run, context={"request": request}).data,
            status=202 if run.status == "running" else 200,
            headers={"Location": _location(request, self.basename, run)},
        )

    @extend_schema(request=None, responses={200: RunDetailSerializer, 202: RunDetailSerializer})
    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None, **kwargs):
        run = run_svc.execute_run(self.get_object().id, only_failed=True)
        return Response(
            RunDetailSerializer(run, context={"request": request}).data,
            status=202 if run.status == "running" else 200,
            headers={"Location": _location(request, self.basename, run)},
        )

    @extend_schema(request=None, responses={202: RunSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None, **kwargs):
        run = run_svc.request_cancel(self.get_object(), request.user)
        return Response(
            RunSerializer(run, context={"request": request}).data,
            status=202,
            headers={"Location": _location(request, self.basename, run)},
        )

    @extend_schema(responses=RunProgressSerializer)
    @action(detail=True, methods=["get"])
    def progress(self, request, pk=None, **kwargs):
        return Response(run_svc.progress(self.get_object()))

    @extend_schema(responses=OpenApiTypes.OBJECT)
    @action(detail=True, methods=["get"])
    def metrics(self, request, pk=None, **kwargs):
        run = self.get_object()
        return Response(run.metrics or {})

    @extend_schema(
        responses={
            (200, "application/json"): OpenApiTypes.OBJECT,
            (200, "text/csv"): OpenApiTypes.BINARY,
            (
                200,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ): OpenApiTypes.BINARY,
        },
    )
    @action(detail=True, methods=["get"], url_path=r"export/(?P<fmt>json|csv|xlsx)")
    def export(self, request, pk=None, fmt=None, **kwargs):
        _require_content_access(request.user)
        run = self.get_object()
        pkg = export_svc.run_package(run)
        stem = f"run-{str(run.id)[:8]}"
        if fmt == "json":
            resp = HttpResponse(
                export_svc.to_json_bytes(pkg), content_type="application/json; charset=utf-8"
            )
            resp["Content-Disposition"] = content_disposition_header(True, f"{stem}.json")
        elif fmt == "csv":
            resp = HttpResponse(
                export_svc.rows_to_csv(pkg["fields"]), content_type="text/csv; charset=utf-8"
            )
            resp["Content-Disposition"] = content_disposition_header(True, f"{stem}-fields.csv")
        else:
            data = export_svc.rows_to_xlsx(
                {
                    "fields": pkg["fields"],
                    "classifications": pkg["classifications"],
                    "segments": pkg["segments"],
                    "ground_truth": pkg["ground_truth"],
                    "errors": pkg["errors"],
                }
            )
            resp = HttpResponse(
                data,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            resp["Content-Disposition"] = content_disposition_header(True, f"{stem}.xlsx")
        return _private_response(resp)


class RunItemViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [DocAIPermission]
    serializer_class = RunItemSerializer
    queryset = q.run_items()
    filterset_class = RunItemFilter
    search_fields = ["document__original_filename", "error_code"]
    ordering_fields = ["modified", "status", "duration_ms"]
    ordering = ["-modified"]


class SegmentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [DocAIPermission]
    action_roles = {"split": REVIEWER, "merge": REVIEWER}
    serializer_class = SegmentSerializer
    queryset = q.segments()
    filterset_class = SegmentFilter
    ordering = ["document", "index"]

    @extend_schema(request=SegmentSplitRequestSerializer, responses=SegmentSerializer(many=True))
    @action(detail=True, methods=["post"], pagination_class=None)
    def split(self, request, pk=None, **kwargs):
        serializer = SegmentSplitRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        segs = review.split_segment(
            self.get_object(),
            request.user,
            at_unit=data["at_unit"],
            category_second=data.get("category"),
            reason=data.get("reason", ""),
        )
        return Response(SegmentSerializer(segs, many=True, context={"request": request}).data)

    @extend_schema(request=SegmentMergeRequestSerializer, responses=SegmentSerializer)
    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None, **kwargs):
        serializer = SegmentMergeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        first = self.get_object()
        second = get_object_or_404(Segment, pk=data["with"])
        seg = review.merge_segments(first, second, request.user, data.get("reason", ""))
        return Response(SegmentSerializer(seg, context={"request": request}).data)


class ClassificationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    permission_classes = [DocAIPermission]
    action_roles = {"accept": REVIEWER, "reclassify": REVIEWER}
    serializer_class = ClassificationSerializer
    queryset = q.classifications()
    filterset_class = ClassificationFilter
    search_fields = ["category", "document__original_filename"]
    ordering_fields = ["score", "created", "category"]
    ordering = ["-created"]

    @extend_schema(request=ReasonRequestSerializer, responses=ClassificationSerializer)
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None, **kwargs):
        serializer = ReasonRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review.accept_classification(
            self.get_object(), request.user, serializer.validated_data.get("reason", "")
        )
        return Response(self.get_serializer(self.get_object()).data)

    @extend_schema(request=ReclassifyRequestSerializer, responses=ClassificationSerializer)
    @action(detail=True, methods=["post"])
    def reclassify(self, request, pk=None, **kwargs):
        serializer = ReclassifyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        review.reclassify(
            self.get_object(),
            request.user,
            category=data["category"],
            reason=data.get("reason", ""),
        )
        return Response(self.get_serializer(self.get_object()).data)


class FieldViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [DocAIPermission]
    action_roles = {"review": REVIEWER, "bulk_review": REVIEWER, "promote": APPROVER}
    serializer_class = FieldSerializer
    queryset = q.fields()
    filterset_class = FieldFilter
    search_fields = ["name", "raw_value", "document__original_filename"]
    ordering_fields = ["score", "name", "created", "review_status", "validation_status"]
    ordering = ["document", "name"]

    @extend_schema(
        request=FieldReviewSerializer,
        responses={200: FieldSerializer},
    )
    @action(detail=True, methods=["post"])
    def review(self, request, pk=None, **kwargs):
        s = FieldReviewSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        field = self.get_object()
        review.act_on_field(
            field, d["action"], request.user, value=d.get("value"), reason=d.get("reason", "")
        )
        field.refresh_from_db()
        return Response(self.get_serializer(field).data)

    @extend_schema(request=ReasonRequestSerializer, responses={201: LabelSerializer})
    @action(detail=True, methods=["post"])
    def promote(self, request, pk=None, **kwargs):
        serializer = ReasonRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        label = review.promote_field_to_ground_truth(
            self.get_object(), request.user, serializer.validated_data.get("reason", "")
        )
        return _created(request, "label", label, LabelSerializer)

    @extend_schema(responses=ReviewHistoryEntrySerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def history(self, request, pk=None, **kwargs):
        _require_content_access(request.user)
        return Response(review.history_for_field(self.get_object()))

    @extend_schema(request=BulkFieldReviewSerializer, responses=BulkReviewResultSerializer)
    @action(detail=False, methods=["post"], url_path="bulk-review")
    def bulk_review(self, request, **kwargs):
        """Select → review summary → typed confirmation → result (§10.5)."""
        s = BulkFieldReviewSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        fields = list(self.get_queryset().filter(id__in=d["field_ids"]))
        done, skipped = [], []
        for f in fields:
            if f.review_status in ("needs_review", "auto_accepted", "pending"):
                review.act_on_field(f, d["action"], request.user, reason=d.get("reason", ""))
                done.append(str(f.id))
            else:
                skipped.append({"id": str(f.id), "reason": f"already {f.review_status}"})
        return Response({"applied": done, "skipped": skipped, "undo_window_seconds": 300})


class LabelViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [DocAIPermission]
    write_role = REVIEWER
    serializer_class = LabelSerializer
    queryset = q.labels()
    filterset_class = LabelFilter
    search_fields = ["field_name", "category", "document__original_filename"]
    ordering = ["-created"]

    @extend_schema(request=LabelCreateSerializer, responses={201: LabelSerializer})
    def create(self, request, **kwargs):
        s = LabelCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        doc = get_object_or_404(Document, pk=d["document"])
        common = {"user": request.user, "notes": d.get("notes", "")}
        m = d["mode"]
        if m == "pdfjs":
            lb = labeling.label_from_pdfjs(
                doc,
                unit_index=d["unit_index"],
                field_name=d["field_name"],
                expected_value=d.get("expected_value") or d["text"],
                text=d["text"],
                rects=d["rects"],
                page_width_pt=d["page_width_pt"],
                page_height_pt=d["page_height_pt"],
                field_type=d.get("field_type", "string"),
                finalize=d["finalize"],
                **common,
            )
        elif m == "word_ids":
            lb = labeling.label_from_word_ids(
                doc,
                unit_index=d["unit_index"],
                field_name=d["field_name"],
                expected_value=d.get("expected_value") or "",
                word_ids=d["word_ids"],
                field_type=d.get("field_type", "string"),
                finalize=d["finalize"],
                **common,
            )
        elif m == "cells":
            lb = labeling.label_from_cells(
                doc,
                unit_index=d["unit_index"],
                field_name=d["field_name"],
                expected_value=d.get("expected_value") or "",
                cell_range=d["cell_range"],
                field_type=d.get("field_type", "string"),
                finalize=d["finalize"],
                **common,
            )
        elif m == "absent":
            lb = labeling.label_absent(doc, field_name=d["field_name"], **common)
        else:
            lb = labeling.label_category(
                doc,
                category=d["category"],
                segment_start=d.get("segment_start"),
                segment_end=d.get("segment_end"),
                **common,
            )
        return _created(request, self.basename, lb, self.get_serializer_class())


class ReviewActionViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    permission_classes = [DocAIPermission]
    serializer_class = ReviewActionSerializer
    queryset = q.review_actions()
    filterset_fields = ["action", "field", "classification", "segment", "actor"]
    ordering = ["-created"]


class EvaluationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [DocAIPermission]
    serializer_class = EvaluationSerializer
    queryset = q.evaluations()
    filterset_fields = ["project", "run", "dataset", "has_ground_truth"]
    ordering = ["-created"]

    @extend_schema(request=EvaluationCreateRequestSerializer, responses={201: EvaluationSerializer})
    def create(self, request, **kwargs):
        serializer = EvaluationCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        run = get_object_or_404(Run, pk=data["run"])
        ev = eval_svc.create_evaluation(
            run,
            request.user,
            data.get("normalization") or {},
            data["numeric_tolerance"],
        )
        return _created(request, self.basename, ev, self.get_serializer_class())


class AuditEventViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [DocAIPermission]
    serializer_class = AuditEventSerializer
    queryset = AuditEvent.objects.select_related("actor")
    filterset_fields = ["action", "object_type", "object_id", "actor", "correlation_id"]
    search_fields = ["action", "object_type", "object_id"]
    ordering = ["-timestamp"]


class DashboardView(APIView):
    permission_classes = [DocAIPermission]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "project",
                OpenApiTypes.UUID,
                OpenApiParameter.QUERY,
                required=False,
                description="Optional project UUID used to scope dashboard counts.",
            )
        ],
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request, **kwargs):
        return Response(dashboard_svc.dashboard(request.query_params.get("project")))


class MeView(APIView):
    permission_classes = [DocAIPermission]

    @extend_schema(responses=UserProfileSerializer)
    def get(self, request, **kwargs):
        from docai.api.auth import user_profile

        return Response(user_profile(request.user))
