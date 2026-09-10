"""django-unfold admin. Read-mostly: results and audit rows are never edited here."""
from django.contrib import admin
from django.db import models
from unfold.admin import ModelAdmin

from docai.forms import PrettyJSONField, PrettyJSONWidget, WorkflowConfigurationAdminForm
from docai.models import (AuditEvent, CategoryDefinition, ClassificationResult, Dataset, Document, Evaluation, ExtractedField,
                          ExtractionTemplate, GroundTruthLabel, ModelConfiguration, ProcessingArtifact, Project,
                          PromptVersion, ReviewAction, ReviewPolicy, Run, RunItem, SchemaVersion, Segment, SourceSpan,
                          SourceUnit, WorkflowConfiguration)


@admin.register(Project)
class ProjectAdmin(ModelAdmin):
    list_display = ("name", "slug", "created", "created_by"); search_fields = ("name", "slug")


@admin.register(Dataset)
class DatasetAdmin(ModelAdmin):
    list_display = ("name", "project", "split", "is_production", "created"); list_filter = ("split", "is_production")


@admin.register(Document)
class DocumentAdmin(ModelAdmin):
    list_display = ("original_filename", "dataset", "file_format", "status", "page_count", "sheet_count", "created")
    list_filter = ("status", "file_format"); search_fields = ("original_filename", "sha256"); readonly_fields = [f.name for f in Document._meta.fields]


@admin.register(WorkflowConfiguration)
class WorkflowAdmin(ModelAdmin):
    form = WorkflowConfigurationAdminForm
    list_display = ("name", "version", "workflow_type", "status", "project", "approved_by", "approved_at")
    list_filter = ("workflow_type", "status"); readonly_fields = ("content_hash", "approved_by", "approved_at")


@admin.register(Run)
class RunAdmin(ModelAdmin):
    list_display = ("name", "workflow", "dataset", "status", "processed_items", "total_items", "failed_items", "created")
    list_filter = ("status",); readonly_fields = [f.name for f in Run._meta.fields]


@admin.register(AuditEvent)
class AuditAdmin(ModelAdmin):
    list_display = ("timestamp", "actor", "action", "object_type", "object_id", "correlation_id")
    list_filter = ("action", "object_type"); readonly_fields = [f.name for f in AuditEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SchemaVersion, ModelConfiguration, ExtractionTemplate, ReviewPolicy,
                Evaluation, ClassificationResult, ExtractedField)
class StructuredDataAdmin(ModelAdmin):
    formfield_overrides = {
        models.JSONField: {"form_class": PrettyJSONField, "widget": PrettyJSONWidget},
    }


for m in (CategoryDefinition, PromptVersion, ProcessingArtifact, SourceUnit, RunItem, Segment,
          SourceSpan, GroundTruthLabel, ReviewAction):
    admin.site.register(m, ModelAdmin)
