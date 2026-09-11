import django_filters as df

from docai.models import (
    ClassificationResult,
    Document,
    ExtractedField,
    GroundTruthLabel,
    Run,
    RunItem,
    Segment,
    WorkflowConfiguration,
)


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
