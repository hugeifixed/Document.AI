"""django-unfold admin. Read-mostly: results and audit rows are never edited here."""

from django.contrib import admin
from django.db import models
from unfold.admin import ModelAdmin

from docai.forms import PrettyJSONField, PrettyJSONWidget, WorkflowConfigurationAdminForm
from docai.models import (
    AuditEvent,
    CategoryDefinition,
    ClassificationResult,
    Dataset,
    Document,
    Evaluation,
    ExtractedField,
    ExtractionTemplate,
    GroundTruthLabel,
    LLMUsageEvent,
    ModelConfiguration,
    ProcessingArtifact,
    Project,
    PromptVersion,
    ReviewAction,
    ReviewPolicy,
    Run,
    RunItem,
    SchemaVersion,
    Segment,
    SourceSpan,
    SourceUnit,
    WorkflowConfiguration,
)


@admin.register(Project)
class ProjectAdmin(ModelAdmin):
    list_display = ("name", "slug", "created", "created_by")
    search_fields = ("name", "slug")


@admin.register(Dataset)
class DatasetAdmin(ModelAdmin):
    list_display = ("name", "project", "split", "is_production", "created")
    list_filter = ("split", "is_production")


@admin.register(Document)
class DocumentAdmin(ModelAdmin):
    list_display = (
        "original_filename",
        "dataset",
        "file_format",
        "status",
        "page_count",
        "sheet_count",
        "created",
    )
    list_filter = ("status", "file_format")
    search_fields = ("original_filename", "sha256")
    readonly_fields = [f.name for f in Document._meta.fields]


@admin.register(WorkflowConfiguration)
class WorkflowAdmin(ModelAdmin):
    form = WorkflowConfigurationAdminForm
    list_display = (
        "name",
        "version",
        "workflow_type",
        "status",
        "project",
        "approved_by",
        "approved_at",
    )
    list_filter = ("workflow_type", "status")
    readonly_fields = ("content_hash", "approved_by", "approved_at")


@admin.register(Run)
class RunAdmin(ModelAdmin):
    list_display = (
        "name",
        "workflow",
        "dataset",
        "status",
        "processed_items",
        "total_items",
        "failed_items",
        "created",
    )
    list_filter = ("status",)
    readonly_fields = [f.name for f in Run._meta.fields]


@admin.register(RunItem)
class RunItemAdmin(ModelAdmin):
    list_display = (
        "document",
        "run",
        "status",
        "stage",
        "attempts",
        "error_code",
        "retryable",
        "modified",
    )
    list_filter = ("status", "retryable", "error_code")
    search_fields = ("document__original_filename", "run__name", "error_code", "correlation_id")
    readonly_fields = [f.name for f in RunItem._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(LLMUsageEvent)
class LLMUsageEventAdmin(ModelAdmin):
    list_display = (
        "created",
        "run",
        "document_name",
        "stage",
        "model_deployment",
        "api_version",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "finish_reason",
        "safety_outcome",
        "outcome",
    )
    list_filter = (
        "provider",
        "stage",
        "outcome",
        "finish_reason",
        "safety_outcome",
        "model_deployment",
        "api_version",
    )
    list_select_related = ("run", "run_item__document")
    search_fields = (
        "run__name",
        "run_item__document__original_filename",
        "provider_request_id",
        "correlation_id",
    )
    readonly_fields = [f.name for f in LLMUsageEvent._meta.fields]

    @admin.display(description="Document", ordering="run_item__document__original_filename")
    def document_name(self, obj):
        return obj.run_item.document.original_filename

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditAdmin(ModelAdmin):
    list_display = ("timestamp", "actor", "action", "object_type", "object_id", "correlation_id")
    list_filter = ("action", "object_type")
    readonly_fields = [f.name for f in AuditEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReviewAction)
class ReviewActionAdmin(ModelAdmin):
    list_display = ("created", "actor", "action", "field", "classification", "segment")
    list_filter = ("action",)
    readonly_fields = [f.name for f in ReviewAction._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(
    SchemaVersion,
    ModelConfiguration,
    ExtractionTemplate,
    ReviewPolicy,
    Evaluation,
    ClassificationResult,
    ExtractedField,
)
class StructuredDataAdmin(ModelAdmin):
    formfield_overrides = {
        models.JSONField: {"form_class": PrettyJSONField, "widget": PrettyJSONWidget},
    }


for m in (
    CategoryDefinition,
    PromptVersion,
    ProcessingArtifact,
    SourceUnit,
    Segment,
    SourceSpan,
    GroundTruthLabel,
):
    admin.site.register(m, ModelAdmin)
