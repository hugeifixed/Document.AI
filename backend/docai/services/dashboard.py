"""Cache reference counts; always read operational status and guidance live."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count

from docai.models import (
    REVIEW_STATUS,
    ClassificationResult,
    Dataset,
    Evaluation,
    ExtractedField,
    Project,
    Run,
    RunItem,
    WorkflowConfiguration,
)

from .journey import project_guidance


def _cache_key(project_id=None) -> str:
    return f"docai:dashboard:counts:v2:{project_id or 'all'}"


_PROJECT_COUNT_KEY = "docai:dashboard:projects:v2"


def invalidate_dashboard(project_id=None) -> None:
    """Expire reference counts after a project, dataset or workflow write commits."""
    keys = [_PROJECT_COUNT_KEY, _cache_key()]
    if project_id:
        keys.append(_cache_key(project_id))
    transaction.on_commit(lambda: cache.delete_many(keys))


def _reference_counts(project_id=None) -> dict:
    key = _cache_key(project_id)
    cached = cache.get_many([_PROJECT_COUNT_KEY, key])
    missing: dict[str, Any] = {}
    if _PROJECT_COUNT_KEY not in cached:
        missing[_PROJECT_COUNT_KEY] = Project.available_objects.count()
    if key not in cached:
        datasets = Dataset.available_objects.all()
        configurations = WorkflowConfiguration.objects.all()
        if project_id:
            datasets = datasets.filter(project_id=project_id)
            configurations = configurations.filter(project_id=project_id)
        missing[key] = {"datasets": datasets.count(), "configurations": configurations.count()}
    if missing:
        # Never publish counts from a transaction which may still roll back.
        transaction.on_commit(
            lambda: cache.set_many(missing, settings.DOCAI_CACHE_TTLS["dashboard"])
        )
    cached.update(missing)
    return {"projects": cached[_PROJECT_COUNT_KEY], **cached[key]}


def dashboard(project_id=None, dataset_id=None) -> dict:
    # Only reference counts are reusable across datasets. Operational counts,
    # recent runs and next-step guidance must reflect the latest committed work.
    runs = Run.objects.all()
    fields = ExtractedField.objects.all()
    cls = ClassificationResult.objects.all()
    if project_id:
        runs = runs.filter(project_id=project_id)
        fields = fields.filter(run__project_id=project_id)
        cls = cls.filter(run__project_id=project_id)
    if dataset_id:
        runs = runs.filter(dataset_id=dataset_id)
        fields = fields.filter(document__dataset_id=dataset_id)
        cls = cls.filter(document__dataset_id=dataset_id)
    evaluations = (
        Evaluation.objects.filter(project_id=project_id) if project_id else Evaluation.objects
    )
    if dataset_id:
        evaluations = evaluations.filter(dataset_id=dataset_id)
    data: dict[str, Any] = {
        **_reference_counts(project_id),
        "runs": {r["status"]: r["n"] for r in runs.values("status").annotate(n=Count("id"))},
        "evaluations": evaluations.count(),
        "review_queue": {
            "fields": fields.filter(review_status=REVIEW_STATUS.needs_review).count(),
            "classifications": cls.filter(review_status=REVIEW_STATUS.needs_review).count(),
        },
        "recent_errors": [
            {
                "run_id": str(i.run_id),
                "document": i.document.original_filename,
                "code": i.error_code,
                "message": i.error_message[:160],
                "at": i.modified.isoformat(),
            }
            for i in RunItem.objects.filter(status="failed", run__in=runs)
            .select_related("document")
            .order_by("-modified")[:10]
        ],
        "recent_runs": [
            {
                "id": str(r.id),
                "name": r.name,
                "status": r.status,
                "workflow": r.workflow.name,
                "processed": r.processed_items,
                "total": r.total_items,
                "created": r.created.isoformat(),
            }
            for r in runs.select_related("workflow").order_by("-created")[:8]
        ],
        "guidance": project_guidance(project_id, dataset_id),
    }
    return data
