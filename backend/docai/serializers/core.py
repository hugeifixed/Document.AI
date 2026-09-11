from django.utils.text import slugify
from rest_framework import serializers

from docai.api.permissions import can_view_content
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
    ModelConfiguration,
    ProcessingArtifact,
    Project,
    PromptVersion,
    ReviewAction,
    Run,
    RunItem,
    SchemaVersion,
    Segment,
    SourceSpan,
    SourceUnit,
    WorkflowConfiguration,
)
from docai.schemas.config import validate_workflow_config

MASK = "•••"


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(trim_whitespace=False, write_only=True)


class _Audited(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField(read_only=True)
    updated_by = serializers.StringRelatedField(read_only=True)


class ProjectSerializer(_Audited):
    slug = serializers.SlugField(required=False, allow_blank=True, max_length=64)

    class Meta:
        model = Project
        fields = ["id", "name", "slug", "description", "created", "modified", "created_by", "updated_by"]
        read_only_fields = ["id", "created", "modified"]

    def validate(self, attrs):
        should_generate = self.instance is None or "slug" in attrs
        if should_generate and not attrs.get("slug"):
            name = attrs.get("name") or getattr(self.instance, "name", "")
            generated_slug = slugify(name)[:64].rstrip("-")
            if not generated_slug:
                raise serializers.ValidationError({
                    "slug": "Enter a slug because one could not be generated from this name."
                })
            attrs["slug"] = generated_slug

        candidate = attrs.get("slug")
        if candidate:
            matches = Project.all_objects.filter(slug=candidate)
            if self.instance is not None:
                matches = matches.exclude(pk=self.instance.pk)
            if matches.exists():
                raise serializers.ValidationError({"slug": "A project with this slug already exists."})
        return attrs


class DatasetSerializer(_Audited):
    document_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Dataset
        fields = ["id", "project", "name", "split", "description", "is_production", "document_count", "created", "modified",
                  "created_by", "updated_by"]
        read_only_fields = ["id", "created", "modified"]


class SourceUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceUnit
        fields = ["id", "kind", "index", "label", "width", "height", "unit", "row_count", "col_count", "service_version"]


class ArtifactSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProcessingArtifact
        fields = ["id", "kind", "stage", "sha256", "size_bytes", "parameters", "page_map", "service_name", "service_version", "created"]


class DocumentSerializer(_Audited):
    dataset_name = serializers.CharField(source="dataset.name", read_only=True)

    class Meta:
        model = Document
        fields = ["id", "dataset", "dataset_name", "original_filename", "source", "mime_type", "file_format", "sha256",
                  "size_bytes", "page_count", "sheet_count", "status", "status_changed", "validation_errors", "metadata",
                  "created", "modified", "created_by", "updated_by"]
        read_only_fields = fields


class DocumentDetailSerializer(DocumentSerializer):
    units = SourceUnitSerializer(many=True, read_only=True)
    artifacts = ArtifactSerializer(many=True, read_only=True)

    class Meta(DocumentSerializer.Meta):
        fields = DocumentSerializer.Meta.fields + ["units", "artifacts"]
        read_only_fields = fields


class CategorySerializer(_Audited):
    class Meta:
        model = CategoryDefinition
        fields = ["id", "project", "key", "name", "description", "distinguishing_evidence", "aliases",
                  "continuation_characteristics", "version", "created", "created_by"]
        read_only_fields = ["id", "version", "created", "created_by"]


class SchemaVersionSerializer(_Audited):
    class Meta:
        model = SchemaVersion
        fields = ["id", "name", "version", "json_schema", "field_definitions", "created", "created_by"]
        read_only_fields = ["id", "version", "json_schema", "created", "created_by"]


class PromptVersionSerializer(_Audited):
    class Meta:
        model = PromptVersion
        fields = ["id", "name", "version", "purpose", "system_prompt", "user_template", "content_hash", "created", "created_by"]
        read_only_fields = ["id", "version", "content_hash", "created", "created_by"]


class ModelConfigurationSerializer(_Audited):
    class Meta:
        model = ModelConfiguration
        fields = ["id", "name", "version", "adapter", "deployment", "parameters", "created", "created_by"]
        read_only_fields = ["id", "version", "created", "created_by"]


class TemplateSerializer(_Audited):
    class Meta:
        model = ExtractionTemplate
        fields = ["id", "project", "name", "version", "document_type", "schema_version", "prompt_version", "model_config",
                  "field_guidance", "validations", "source_expectations", "chunking", "status", "created", "created_by"]
        read_only_fields = ["id", "version", "status", "created", "created_by"]


class WorkflowSerializer(_Audited):
    approved_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = WorkflowConfiguration
        fields = ["id", "project", "name", "version", "workflow_type", "config", "content_hash", "status", "approved_by",
                  "approved_at", "created", "modified", "created_by", "updated_by"]
        read_only_fields = ["id", "version", "content_hash", "status", "approved_by", "approved_at", "created", "modified"]

    def validate(self, attrs):
        wt = attrs.get("workflow_type") or getattr(self.instance, "workflow_type", None)
        cfg = attrs.get("config")
        if wt and cfg is not None:
            try:
                attrs["config"] = validate_workflow_config(wt, cfg)
            except ValueError as exc:
                raise serializers.ValidationError({"config": str(exc)[:600]}) from None
        return attrs


class RunSerializer(_Audited):
    workflow_name = serializers.CharField(source="workflow.name", read_only=True)
    workflow_type = serializers.CharField(source="workflow.workflow_type", read_only=True)
    dataset_name = serializers.CharField(source="dataset.name", read_only=True)

    class Meta:
        model = Run
        fields = ["id", "project", "workflow", "workflow_name", "workflow_type", "dataset", "dataset_name", "name", "status",
                  "status_changed", "stage", "total_items", "processed_items", "failed_items", "started_at", "finished_at",
                  "cancel_requested", "config_hash", "prompt_versions", "schema_versions", "model_deployment", "layout_adapter",
                  "llm_adapter", "sample_size", "warnings", "errors", "created", "modified", "created_by", "updated_by"]
        read_only_fields = [f for f in fields if f not in ("project", "workflow", "dataset", "name", "sample_size")]


class RunDetailSerializer(RunSerializer):
    class Meta(RunSerializer.Meta):
        fields = RunSerializer.Meta.fields + ["config_snapshot", "metrics", "model_parameters"]
        read_only_fields = [f for f in fields if f not in ("project", "workflow", "dataset", "name", "sample_size")]


class RunCreateSerializer(serializers.Serializer):
    project = serializers.UUIDField()
    workflow = serializers.UUIDField()
    dataset = serializers.UUIDField()
    name = serializers.CharField(required=False, allow_blank=True, max_length=160)
    sample_size = serializers.IntegerField(required=False, min_value=1)
    document_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    execute = serializers.BooleanField(default=True)


class RunItemSerializer(serializers.ModelSerializer):
    document_name = serializers.CharField(source="document.original_filename", read_only=True)

    class Meta:
        model = RunItem
        fields = ["id", "run", "document", "document_name", "status", "stage", "attempts", "error_code", "error_message",
                  "retryable", "duration_ms", "correlation_id", "modified"]


class _Masking(serializers.ModelSerializer):
    sensitive = ()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        req = self.context.get("request")
        if req is not None and not can_view_content(req.user):
            for k in self.sensitive:
                if data.get(k) not in (None, ""):
                    data[k] = MASK
        return data


class SourceSpanSerializer(_Masking):
    unit_index = serializers.IntegerField(source="unit.index", read_only=True)
    unit_kind = serializers.CharField(source="unit.kind", read_only=True)
    sensitive = ("text",)

    class Meta:
        model = SourceSpan
        fields = ["id", "unit", "unit_index", "unit_kind", "text", "offset_start", "offset_end", "polygon", "word_ids",
                  "cell_range", "mapping_method", "match_score", "exceptions", "origin"]


class SegmentSerializer(_Masking):
    spans = SourceSpanSerializer(many=True, read_only=True)
    document_name = serializers.CharField(source="document.original_filename", read_only=True)
    sensitive = ("evidence",)

    class Meta:
        model = Segment
        fields = ["id", "run", "document", "document_name", "index", "start_unit", "end_unit", "category", "score", "method",
                  "evidence", "continuation_of", "review_status", "spans", "created", "modified"]


class ClassificationSerializer(_Masking):
    spans = SourceSpanSerializer(many=True, read_only=True)
    document_name = serializers.CharField(source="document.original_filename", read_only=True)
    prompt = serializers.StringRelatedField(source="prompt_version", read_only=True)
    schema = serializers.StringRelatedField(source="schema_version", read_only=True)
    sensitive = ("llm_evidence", "matched_evidence")

    class Meta:
        model = ClassificationResult
        fields = ["id", "run", "document", "document_name", "segment", "category", "reviewed_category", "score", "method",
                  "rule_score", "matched_evidence", "excluded_evidence", "llm_evidence", "model_deployment", "prompt", "schema",
                  "rule_version", "review_status", "spans", "created", "modified"]


class FieldSerializer(_Masking):
    spans = SourceSpanSerializer(many=True, read_only=True)
    document_name = serializers.CharField(source="document.original_filename", read_only=True)
    prompt = serializers.StringRelatedField(source="prompt_version", read_only=True)
    schema = serializers.StringRelatedField(source="schema_version", read_only=True)
    sensitive = ("raw_value", "normalized_value", "reviewed_value", "source_text", "suggested_correction")

    class Meta:
        model = ExtractedField
        fields = ["id", "run", "document", "document_name", "segment", "name", "field_type", "raw_value", "normalized_value",
                  "reviewed_value", "score", "source_text", "method", "strategy", "fallback_used", "model_deployment", "prompt",
                  "schema", "api_version", "validation_status", "validation_messages", "suggested_correction", "review_status",
                  "grounded", "spans", "created", "modified"]


class ReviewActionSerializer(_Masking):
    actor = serializers.StringRelatedField(read_only=True)
    sensitive = ("before", "after", "reason")

    class Meta:
        model = ReviewAction
        fields = ["id", "actor", "action", "field", "classification", "segment", "before", "after", "reason", "correlation_id", "created"]


class LabelSerializer(_Masking):
    spans = SourceSpanSerializer(many=True, read_only=True)
    labeler = serializers.StringRelatedField(read_only=True)
    unit_index = serializers.IntegerField(source="unit.index", read_only=True)
    sensitive = ("expected_value", "normalized_value", "pdfjs_span", "azure_span")

    class Meta:
        model = GroundTruthLabel
        fields = ["id", "document", "unit", "unit_index", "segment_start", "segment_end", "kind", "field_name", "category",
                  "expected_value", "normalized_value", "is_absent", "pdfjs_span", "azure_span", "mapping_method", "match_score",
                  "mapping_exceptions", "cell_range", "labeler", "version", "status", "notes", "spans", "created"]


class LabelCreateSerializer(serializers.Serializer):
    document = serializers.UUIDField()
    mode = serializers.ChoiceField(choices=["pdfjs", "word_ids", "cells", "absent", "category"])
    field_name = serializers.CharField(required=False, allow_blank=True)
    field_type = serializers.CharField(required=False, default="string")
    expected_value = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    unit_index = serializers.IntegerField(required=False, min_value=0)
    text = serializers.CharField(required=False, allow_blank=True)
    rects = serializers.ListField(child=serializers.DictField(), required=False)
    page_width_pt = serializers.FloatField(required=False)
    page_height_pt = serializers.FloatField(required=False)
    word_ids = serializers.ListField(child=serializers.CharField(), required=False)
    cell_range = serializers.CharField(required=False)
    category = serializers.CharField(required=False)
    segment_start = serializers.IntegerField(required=False, min_value=0)
    segment_end = serializers.IntegerField(required=False, min_value=0)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    finalize = serializers.BooleanField(default=True)

    def validate(self, a):
        m = a["mode"]
        need = {"pdfjs": ["field_name", "unit_index", "text", "rects", "page_width_pt", "page_height_pt"],
                "word_ids": ["field_name", "unit_index", "word_ids"], "cells": ["field_name", "unit_index", "cell_range"],
                "absent": ["field_name"], "category": ["category"]}[m]
        missing = [k for k in need if k not in a]
        if missing:
            raise serializers.ValidationError(
                dict.fromkeys(missing, f"This field is required for mode '{m}'.")
            )
        return a


class EvaluationSerializer(serializers.ModelSerializer):
    run_name = serializers.CharField(source="run.name", read_only=True)

    class Meta:
        model = Evaluation
        fields = ["id", "project", "run", "run_name", "dataset", "predictions_source", "normalization", "metrics",
                  "has_ground_truth", "created"]
        read_only_fields = ["id", "metrics", "has_ground_truth", "created", "predictions_source"]


class AuditEventSerializer(_Masking):
    actor = serializers.StringRelatedField(read_only=True)
    sensitive = ("before_ref", "after_ref", "reason")

    class Meta:
        model = AuditEvent
        fields = ["id", "actor", "action", "object_type", "object_id", "timestamp", "correlation_id", "before_ref", "after_ref", "reason"]


class FieldReviewSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["accept", "correct", "reject", "mark_absent", "note", "promote"])
    value = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class BulkFieldReviewSerializer(serializers.Serializer):
    field_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=500)
    action = serializers.ChoiceField(choices=["accept", "reject"])
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    confirm_count = serializers.IntegerField(help_text="Must equal len(field_ids): typed confirmation for bulk actions.")

    def validate(self, a):
        if a["confirm_count"] != len(a["field_ids"]):
            raise serializers.ValidationError({"confirm_count": "Confirmation count does not match the selection."})
        return a
