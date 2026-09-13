import django_filters as df
from django.db.models import Exists, OuterRef, Q, Subquery
from rest_framework.filters import SearchFilter

from docai.models import (
    ClassificationResult,
    Document,
    ExtractedField,
    GroundTruthLabel,
    ProcessingArtifact,
    Run,
    RunItem,
    Segment,
    SourceUnit,
    WorkflowConfiguration,
)


class DocumentSearchFilter(SearchFilter):
    """Search current OCR text without joining every historical representation."""

    def filter_queryset(self, request, queryset, view):
        latest = (
            ProcessingArtifact.objects.filter(document_id=OuterRef("document_id"), kind="layout")
            .order_by("-created", "-id")
            .values("pk")[:1]
        )
        for term in self.get_search_terms(request):
            matching_units = SourceUnit.objects.filter(
                document_id=OuterRef("pk"),
                layout_artifact_id=Subquery(latest),
                text_preview__icontains=term,
            )
            queryset = queryset.filter(
                Q(original_filename__icontains=term)
                | Q(sha256__icontains=term)
                | Q(Exists(matching_units))
            )
        return queryset


class DocumentFilter(df.FilterSet):
    class Meta:
        model = Document
        fields = {
            "dataset": ["exact"],
            "status": ["exact", "in"],
            "file_format": ["exact", "in"],
            "created": ["gte", "lte"],
            "sha256": ["exact"],
        }


class RunFilter(df.FilterSet):
    document = df.UUIDFilter(field_name="items__document")

    class Meta:
        model = Run
        fields = {
            "project": ["exact"],
            "dataset": ["exact"],
            "workflow": ["exact"],
            "status": ["exact", "in"],
            "created": ["gte", "lte"],
            "config_hash": ["exact"],
        }


class RunItemFilter(df.FilterSet):
    class Meta:
        model = RunItem
        fields = {
            "run": ["exact"],
            "document": ["exact"],
            "status": ["exact", "in"],
            "error_code": ["exact"],
        }


class FieldFilter(df.FilterSet):
    min_score = df.NumberFilter(field_name="score", lookup_expr="gte")
    max_score = df.NumberFilter(field_name="score", lookup_expr="lte")
    project = df.UUIDFilter(field_name="run__project")
    dataset = df.UUIDFilter(field_name="document__dataset")

    class Meta:
        model = ExtractedField
        fields = {
            "run": ["exact"],
            "document": ["exact"],
            "segment": ["exact"],
            "name": ["exact", "in"],
            "review_status": ["exact", "in"],
            "validation_status": ["exact", "in"],
            "grounded": ["exact"],
        }


class ClassificationFilter(df.FilterSet):
    project = df.UUIDFilter(field_name="run__project")
    dataset = df.UUIDFilter(field_name="document__dataset")

    class Meta:
        model = ClassificationResult
        fields = {
            "run": ["exact"],
            "document": ["exact"],
            "category": ["exact", "in"],
            "method": ["exact"],
            "review_status": ["exact", "in"],
        }


class SegmentFilter(df.FilterSet):
    class Meta:
        model = Segment
        fields = {
            "run": ["exact"],
            "document": ["exact"],
            "category": ["exact", "in"],
            "review_status": ["exact", "in"],
        }


class LabelFilter(df.FilterSet):
    class Meta:
        model = GroundTruthLabel
        fields = {
            "document": ["exact"],
            "kind": ["exact"],
            "field_name": ["exact"],
            "status": ["exact", "in"],
            "document__dataset": ["exact"],
        }


class WorkflowFilter(df.FilterSet):
    class Meta:
        model = WorkflowConfiguration
        fields = {
            "project": ["exact"],
            "workflow_type": ["exact"],
            "status": ["exact", "in"],
            "name": ["exact"],
        }
