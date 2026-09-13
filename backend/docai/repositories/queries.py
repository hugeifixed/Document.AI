"""Data-access helpers with select_related/prefetch_related so list endpoints
never N+1. Viewsets take their base querysets from here."""

from django.db.models import Q

from docai.models import (
    ClassificationResult,
    Dataset,
    Document,
    Evaluation,
    ExtractedField,
    ExtractionTemplate,
    GroundTruthLabel,
    Project,
    ReviewAction,
    Run,
    RunItem,
    Segment,
    WorkflowConfiguration,
)


def projects():
    return Project.available_objects.select_related("created_by", "updated_by")


def datasets():
    return Dataset.available_objects.select_related("project", "created_by")


def documents():
    return Document.objects.select_related("dataset", "dataset__project", "created_by")


def workflows():
    return WorkflowConfiguration.objects.select_related("project", "created_by", "approved_by")


def templates():
    return ExtractionTemplate.objects.select_related(
        "project", "schema_version", "prompt_version", "model_config"
    )


def runs():
    return Run.objects.select_related("project", "workflow", "dataset", "created_by")


def run_items():
    return RunItem.objects.select_related("run", "document")


def segments():
    return Segment.objects.select_related("run", "document", "continuation_of").prefetch_related(
        "spans__unit"
    )


def classifications():
    return ClassificationResult.objects.select_related(
        "run", "document", "segment", "prompt_version", "schema_version"
    ).prefetch_related("spans__unit")


def fields():
    return ExtractedField.objects.select_related(
        "run", "document", "segment", "prompt_version", "schema_version"
    ).prefetch_related("spans__unit")


def labels():
    return GroundTruthLabel.objects.select_related("document", "unit", "labeler").prefetch_related(
        "spans__unit"
    )


def review_actions():
    return ReviewAction.objects.select_related("actor", "field", "classification", "segment")


def evaluations():
    return Evaluation.objects.select_related("project", "run", "dataset")


def document_neighbors(document, run_id=None):
    """Two bounded lookups in the document list's default (-created, id) order.

    The caller authorizes the anchor and validates any run membership. All neighbors
    share its dataset/project. No offsets, full document payloads, or LOB sorting.
    """
    candidates = Document.objects.filter(dataset_id=document.dataset_id)
    if run_id:
        candidates = candidates.filter(run_items__run_id=run_id)
    summaries = candidates.values("id", "original_filename")
    previous = (
        summaries.filter(
            Q(created__gt=document.created) | Q(created=document.created, pk__lt=document.pk)
        )
        .order_by("created", "-id")
        .first()
    )
    following = (
        summaries.filter(
            Q(created__lt=document.created) | Q(created=document.created, pk__gt=document.pk)
        )
        .order_by("-created", "id")
        .first()
    )
    return {
        "scope": "run" if run_id else "dataset",
        "run": run_id,
        "previous": previous,
        "next": following,
    }
