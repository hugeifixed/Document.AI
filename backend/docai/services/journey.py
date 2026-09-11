"""Read-only facts used by the frontend to guide users through the document lifecycle."""

from __future__ import annotations

from django.db.models import Count, QuerySet

from docai.models import (
    CONFIG_STATUS,
    DOC_STATUS,
    LABEL_STATUS,
    REVIEW_STATUS,
    RUN_STATUS,
    Dataset,
    Document,
    Evaluation,
    GroundTruthLabel,
    Run,
    WorkflowConfiguration,
)

_RUNNABLE_DOCUMENT_STATUSES = [
    DOC_STATUS.validated,
    DOC_STATUS.processed,
    DOC_STATUS.failed,
]
_RUNNABLE_WORKFLOW_STATUSES = [CONFIG_STATUS.draft, CONFIG_STATUS.approved]
_TERMINAL_RUN_STATUSES = [
    RUN_STATUS.succeeded,
    RUN_STATUS.partial,
    RUN_STATUS.failed,
    RUN_STATUS.cancelled,
]


def _review_counts(run: Run) -> dict[str, int]:
    return {
        "fields": run.fields.filter(review_status=REVIEW_STATUS.needs_review).count(),
        "classifications": run.classifications.filter(
            review_status=REVIEW_STATUS.needs_review
        ).count(),
    }


def run_guidance(run: Run) -> dict:
    """Return lifecycle facts for one run without prescribing UI wording or routes."""
    if run.status not in _TERMINAL_RUN_STATUSES:
        return {
            "review": {"fields": 0, "classifications": 0},
            "results": 0,
            "ground_truth": {"labels": 0, "documents": 0},
            "evaluations": {"count": 0, "latest_id": None, "has_ground_truth": None},
            "export_ready": False,
        }
    labels = GroundTruthLabel.objects.filter(
        document__dataset=run.dataset,
        status=LABEL_STATUS.final,
    )
    evaluations = Evaluation.objects.filter(run=run).order_by("-created")
    latest_evaluation = evaluations.first()
    result_count = run.fields.count() + run.classifications.count()
    return {
        "review": _review_counts(run),
        "results": result_count,
        "ground_truth": {
            "labels": labels.count(),
            "documents": labels.values("document_id").distinct().count(),
        },
        "evaluations": {
            "count": evaluations.count(),
            "latest_id": str(latest_evaluation.id) if latest_evaluation else None,
            "has_ground_truth": latest_evaluation.has_ground_truth if latest_evaluation else None,
        },
        "export_ready": run.status in _TERMINAL_RUN_STATUSES and run.processed_items > 0,
    }


def _workflow_facts(project_id) -> dict:
    workflows = WorkflowConfiguration.objects.filter(
        project_id=project_id,
        status__in=_RUNNABLE_WORKFLOW_STATUSES,
    ).exclude(workflow_type="evaluate")
    status_counts = {
        row["status"]: row["count"]
        for row in workflows.values("status").annotate(count=Count("id"))
    }
    suggested = workflows.filter(status=CONFIG_STATUS.approved).order_by("-created").first()
    if suggested is None:
        suggested = workflows.order_by("-created").first()
    return {
        "runnable": workflows.count(),
        "approved": status_counts.get(CONFIG_STATUS.approved, 0),
        "draft": status_counts.get(CONFIG_STATUS.draft, 0),
        "suggested": (
            {
                "id": str(suggested.id),
                "name": suggested.name,
                "version": suggested.version,
                "status": suggested.status,
            }
            if suggested
            else None
        ),
    }


def _latest_run_payload(runs: QuerySet[Run]) -> dict | None:
    latest = runs.select_related("workflow", "dataset").order_by("-created").first()
    if latest is None:
        return None
    return {
        "id": str(latest.id),
        "name": latest.name,
        "workflow": latest.workflow.name,
        "status": latest.status,
        "processed": latest.processed_items,
        "total": latest.total_items,
        "failed": latest.failed_items,
        "created": latest.created.isoformat(),
        "guidance": run_guidance(latest),
    }


def project_guidance(project_id, dataset_id=None) -> dict:
    """Return project/dataset readiness facts for the frontend journey resolver."""
    if not project_id:
        return {
            "dataset": None,
            "documents": {"total": 0, "runnable": 0, "blocked": 0, "new_for_run": 0},
            "workflows": {"runnable": 0, "approved": 0, "draft": 0, "suggested": None},
            "latest_run": None,
        }

    workflow_facts = _workflow_facts(project_id)
    dataset = None
    if dataset_id:
        dataset = Dataset.available_objects.filter(pk=dataset_id, project_id=project_id).first()

    if dataset is None:
        return {
            "dataset": None,
            "documents": {"total": 0, "runnable": 0, "blocked": 0, "new_for_run": 0},
            "workflows": workflow_facts,
            "latest_run": None,
        }

    documents = Document.objects.filter(dataset=dataset)
    runnable_documents = documents.filter(status__in=_RUNNABLE_DOCUMENT_STATUSES)
    runs = Run.objects.filter(project_id=project_id, dataset=dataset)
    latest_run = runs.order_by("-created").first()
    new_for_run = (
        runnable_documents.exclude(run_items__run=latest_run).distinct().count()
        if latest_run
        else runnable_documents.count()
    )
    return {
        "dataset": {
            "id": str(dataset.id),
            "name": dataset.name,
            "split": dataset.split,
            "is_production": dataset.is_production,
        },
        "documents": {
            "total": documents.count(),
            "runnable": runnable_documents.count(),
            "blocked": documents.exclude(status__in=_RUNNABLE_DOCUMENT_STATUSES).count(),
            "new_for_run": new_for_run,
        },
        "workflows": workflow_facts,
        "latest_run": _latest_run_payload(runs),
    }
