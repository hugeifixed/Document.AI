"""Dashboard aggregates: cached (TTL from settings) and invalidated by signals."""

from __future__ import annotations

from typing import Any, cast

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


def _cache_key(project_id=None) -> str:
    return f"docai:dashboard{':' + str(project_id) if project_id else ''}"


def invalidate_dashboard(project_id=None) -> None:
    """Expire global and project dashboard values after the current write commits."""
    keys = ["docai:dashboard"]
    if project_id:
        keys.append(_cache_key(project_id))
    transaction.on_commit(lambda: cache.delete_many(keys))


def dashboard(project_id=None) -> dict:
    key = _cache_key(project_id)
    cached_data = cache.get(key)
    if cached_data is not None:
        return cast(dict[str, Any], cached_data)
    runs = Run.objects.all()
    fields = ExtractedField.objects.all()
    cls = ClassificationResult.objects.all()
    if project_id:
        runs = runs.filter(project_id=project_id)
        fields = fields.filter(run__project_id=project_id)
        cls = cls.filter(run__project_id=project_id)
    data: dict[str, Any] = {
        "projects": Project.available_objects.count(),
        "datasets": Dataset.available_objects.filter(project_id=project_id).count()
        if project_id
        else Dataset.available_objects.count(),
        "configurations": (
            WorkflowConfiguration.objects.filter(project_id=project_id)
            if project_id
            else WorkflowConfiguration.objects
        ).count(),
        "runs": {r["status"]: r["n"] for r in runs.values("status").annotate(n=Count("id"))},
        "evaluations": (
            Evaluation.objects.filter(project_id=project_id) if project_id else Evaluation.objects
        ).count(),
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
    }
    cache.set(key, data, settings.DOCAI_CACHE_TTLS["dashboard"])
    return data
