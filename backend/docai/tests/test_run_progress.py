from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from django.db import DatabaseError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from pydantic import ValidationError

from docai.adapters.azure_identity import with_retries
from docai.models import DOC_STATUS, ITEM_STATUS, RUN_STATUS, Document, RunItem
from docai.schemas.progress import ProcessingProgress, ProgressCounter, ProgressSegment
from docai.services import ingestion, run_execution, runs
from docai.services.run_progress import ProgressRecorder, snapshot


def _documents(dataset, admin, count: int) -> list[Document]:
    return [
        Document.objects.create(
            dataset=dataset,
            original_filename=f"document-{index}.pdf",
            mime_type="application/pdf",
            file_format="pdf",
            sha256=f"{index:064x}",
            size_bytes=100,
            storage_path=f"documents/{index}.pdf",
            status=DOC_STATUS.validated,
            created_by=admin,
        )
        for index in range(count)
    ]


def _run_with_documents(project, dataset, admin, sample_workflow, count: int):
    _documents(dataset, admin, count)
    return runs.create_run(project, sample_workflow, dataset, admin)


def test_progress_schema_rejects_impossible_or_unbounded_values():
    with pytest.raises(ValidationError):
        ProgressCounter(completed=2, total=1, unit="pages")
    with pytest.raises(ValidationError):
        ProgressSegment(current=2, total=1)
    with pytest.raises(ValidationError):
        ProcessingProgress.model_validate(
            {
                **snapshot("analyzing", "extracting"),
                "completed_phases": ["queued", "queued"],
            }
        )
    invalid_timestamp = snapshot("analyzing", "extracting")
    invalid_timestamp["phase_started_at"] = "2026-01-01T12:00:00"
    with pytest.raises(ValidationError):
        ProcessingProgress.model_validate(invalid_timestamp)


def test_snapshot_discards_invalid_legacy_json_and_keeps_a_bounded_phase_set():
    value = snapshot(
        "analyzing",
        "extracting",
        previous={"phase": "old-client-shape"},
        counter={"completed": 0, "total": 2, "unit": "chunks"},
    )
    assert value["completed_phases"] == []
    assert value["counter"] == {"completed": 0, "total": 2, "unit": "chunks"}
    assert ProcessingProgress.model_validate(value)


def test_provider_retry_reports_the_real_schedule_and_resume():
    class Throttled(Exception):
        status_code = 429

    attempts = 0
    milestones: list[datetime | None] = []

    def call():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise Throttled
        return "ok"

    with patch("docai.adapters.azure_identity.time.sleep") as sleep:
        assert (
            with_retries(
                call,
                max_retries=1,
                base_delay=2,
                retry_observer=milestones.append,
            )
            == "ok"
        )

    assert sleep.call_args.args == (2,)
    assert milestones[0] is not None
    assert milestones[0] > timezone.now()
    assert milestones[1] is None


@pytest.mark.django_db
def test_recorder_throttles_counts_but_never_a_new_segment_or_terminal_state(
    project, dataset, admin, sample_workflow
):
    run = _run_with_documents(project, dataset, admin, sample_workflow, 1)
    item = run.items.get()
    item.status = ITEM_STATUS.running
    item.attempts = 1
    item.worker_task_id = "task-1"
    item.save(update_fields=["status", "attempts", "worker_task_id", "status_changed", "modified"])
    recorder = ProgressRecorder(item.pk, 1, "task-1", throttle_seconds=60)

    assert recorder.record(
        "analyzing",
        "extracting",
        completed=0,
        total=2,
        unit="chunks",
        segment_current=1,
        segment_total=2,
    )
    assert not recorder.record(
        "analyzing",
        "extracting",
        completed=1,
        total=2,
        unit="chunks",
        segment_current=1,
        segment_total=2,
    )
    assert recorder.record(
        "analyzing",
        "extracting",
        completed=0,
        total=1,
        unit="chunks",
        segment_current=2,
        segment_total=2,
    )
    item.refresh_from_db()
    assert item.processing_progress["segment"] == {"current": 2, "total": 2}
    assert item.processing_progress["counter"]["completed"] == 0

    retry_at = timezone.now() + timedelta(seconds=2)
    assert recorder.record("analyzing", "retry_wait", retry_at=retry_at)
    item.refresh_from_db()
    assert item.stage == "retry_wait"
    assert recorder.record("analyzing", "extracting")
    item.refresh_from_db()
    assert item.stage == "workflow"

    assert recorder.record("complete", "complete")
    item.refresh_from_db()
    assert item.processing_progress["operation"] == "complete"


@pytest.mark.django_db
def test_recorder_rejects_stale_attempt_and_does_not_poison_outer_transaction(
    project, dataset, admin, sample_workflow
):
    run = _run_with_documents(project, dataset, admin, sample_workflow, 1)
    item = run.items.get()
    item.status = ITEM_STATUS.running
    item.attempts = 2
    item.save(update_fields=["status", "attempts", "status_changed", "modified"])

    assert not ProgressRecorder(item.pk, 1).record("analyzing", "extracting")
    with transaction.atomic():
        with patch(
            "django.db.models.query.QuerySet.update", side_effect=DatabaseError("telemetry")
        ):
            assert not ProgressRecorder(item.pk, 2).record("analyzing", "extracting")
        assert RunItem.objects.filter(pk=item.pk).exists()


@pytest.mark.django_db
def test_new_claim_resets_retry_snapshot(project, dataset, admin, sample_workflow):
    run = _run_with_documents(project, dataset, admin, sample_workflow, 1)
    item = run.items.get()
    item.attempts = 1
    item.worker_task_id = "task-1"
    item.processing_progress = snapshot(
        "analyzing",
        "retry_wait",
        counter={"completed": 1, "total": 2, "unit": "chunks"},
        segment={"current": 1, "total": 2},
        retry_at=timezone.now() + timedelta(seconds=30),
    )
    item.save(update_fields=["attempts", "worker_task_id", "processing_progress", "modified"])

    claimed, accepted = run_execution._claim_item(item.pk, "task-1")

    assert accepted and claimed.attempts == 2
    assert claimed.processing_progress["phase"] == "queued"
    assert claimed.processing_progress["operation"] == "queued"
    assert claimed.processing_progress["counter"] is None
    assert claimed.processing_progress["segment"] is None
    assert claimed.processing_progress["retry_at"] is None


@pytest.mark.django_db
def test_retry_schedule_is_guarded_by_claim_and_records_actual_time(
    project, dataset, admin, sample_workflow
):
    run = _run_with_documents(project, dataset, admin, sample_workflow, 1)
    item = run.items.get()
    item.status = ITEM_STATUS.queued
    item.attempts = 1
    item.worker_task_id = "task-1"
    item.save(update_fields=["status", "attempts", "worker_task_id", "status_changed", "modified"])
    retry_at = timezone.now() + timedelta(seconds=15)

    assert run_execution.record_retry_schedule(
        str(item.pk), attempt=1, task_id="task-1", retry_at=retry_at
    )
    assert not run_execution.record_retry_schedule(
        str(item.pk), attempt=1, task_id="obsolete-task", retry_at=retry_at
    )
    item.refresh_from_db()
    progress = ProcessingProgress.model_validate(item.processing_progress)
    assert progress.operation == "retry_wait"
    assert progress.retry_at == retry_at


@pytest.mark.django_db
def test_real_local_workflow_finishes_with_completed_phases(
    project, dataset, admin, sample_workflow, w2_pdf
):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = runs.create_run(project, sample_workflow, dataset, admin)
    item = run.items.get()

    assert run_execution.process_item(item.pk) == ITEM_STATUS.succeeded

    item.refresh_from_db()
    progress = ProcessingProgress.model_validate(item.processing_progress)
    assert progress.phase == "complete"
    assert progress.operation == "complete"
    assert {"queued", "reading_document", "analyzing", "saving_results"} <= set(
        progress.completed_phases
    )


@pytest.mark.django_db
def test_progress_uses_scalar_aggregates_stable_activity_and_cautious_eta(
    project, dataset, admin, sample_workflow
):
    run = _run_with_documents(project, dataset, admin, sample_workflow, 6)
    started = timezone.now() - timedelta(seconds=30)
    RunItem.objects.filter(run=run).update(progress_updated_at=started)
    items = list(run.items.order_by("created", "id"))
    latest_success = started + timedelta(seconds=30)
    for offset, item in enumerate(items[:3]):
        RunItem.objects.filter(pk=item.pk).update(
            status=ITEM_STATUS.succeeded,
            modified=latest_success - timedelta(seconds=2 - offset),
        )
    RunItem.objects.filter(pk=items[3].pk).update(status=ITEM_STATUS.running)
    RunItem.objects.filter(pk=items[4].pk).update(status=ITEM_STATUS.queued, stage="retry_wait")
    RunItem.objects.filter(pk=items[5].pk).update(status=ITEM_STATUS.queued, stage="queued")
    # Retry-wait suppresses ETA even when the sample count is otherwise sufficient.
    run.status = RUN_STATUS.running
    run.stage = "processing"
    run.started_at = started
    run.save(update_fields=["status", "stage", "started_at", "status_changed", "modified"])

    with CaptureQueriesContext(connection) as queries:
        result = run_execution.progress(run)

    assert len(queries) == 2
    aggregate_sql = queries[0]["sql"].lower()
    assert "processing_progress" not in aggregate_sql
    activity_sql = queries[1]["sql"].lower()
    assert "json_extract" not in aggregate_sql + activity_sql
    assert "processing_progress" not in activity_sql.split("order by", maxsplit=1)[1]
    assert "created" in activity_sql.split("order by", maxsplit=1)[1]
    assert result["estimated_finish_at"] is None
    assert [item.id for item in result["activity_items"]] == [
        items[3].id,
        items[4].id,
        items[5].id,
    ]
    assert result["last_milestone_at"] == started

    RunItem.objects.filter(pk=items[4].pk).update(stage="queued")
    result = run_execution.progress(run)
    assert result["estimated_finish_at"] == latest_success + timedelta(seconds=30)
    assert result["estimated_seconds_remaining"] is not None


@pytest.mark.django_db
def test_progress_api_serializes_empty_snapshot_as_null_and_run_items_default_to_fifty(
    project, dataset, admin, sample_workflow, api
):
    run = _run_with_documents(project, dataset, admin, sample_workflow, 51)
    first = run.items.order_by("created", "id").first()
    assert first is not None
    RunItem.objects.filter(pk=first.pk).update(processing_progress={}, progress_updated_at=None)

    page = api.get("/api/v1/run-items/", {"run": str(run.pk)})
    progress_response = api.get(f"/api/v1/runs/{run.pk}/progress/")

    assert page.status_code == 200
    page_data = page.json()["data"]
    assert page_data["page_size"] == 50
    assert len(page_data["results"]) == 50
    assert page_data["results"][0]["processing_progress"] is None
    assert progress_response.status_code == 200
    progress_data = progress_response.json()["data"]
    assert {"as_of", "last_milestone_at", "activity_items", "estimated_finish_at"} <= set(
        progress_data
    )
    assert len(progress_data["activity_items"]) == 5
