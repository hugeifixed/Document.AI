"""Integration coverage for workflow invocation and inline/polled JSON."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from docai.exceptions import IntegrationError
from docai.models import CONFIG_STATUS, Dataset, Document, Project, Run, WorkflowInvocation
from docai.services import governance, ingestion
from docai.services.invocations import expired_cleanup_queryset

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.DOCAI_DATA_DIR = tmp_path


@pytest.fixture(autouse=True)
def hold_scheduled_runs(monkeypatch):
    """Keep API tests deterministic while asserting the asynchronous contract."""
    monkeypatch.setattr(
        "docai.api.invocation.execution.schedule_run",
        lambda pk: Run.objects.get(pk=pk),
    )


def invoke_url(workflow):
    return f"/api/v1/workflows/{workflow.pk}/invoke/"


def upload():
    return SimpleUploadedFile("sample.txt", b"Employee name: Alex Sample\nWages: 1000")


def invoke(api, workflow, data, *, key="invocation-1", format="json"):
    if workflow.status != CONFIG_STATUS.approved:
        workflow.status = CONFIG_STATUS.approved
        workflow.save(update_fields=["status", "modified"])
    return api.post(
        invoke_url(workflow),
        data,
        format=format,
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_upload_returns_async_handle_and_bounded_poll(api, dataset, sample_workflow):
    response = invoke(
        api,
        sample_workflow,
        {"dataset": str(dataset.pk), "files": [upload()]},
        format="multipart",
    )
    assert response.status_code == 202, response.content
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert data["client_reference"] == ""
    assert response["Retry-After"] == "2"
    assert "no-store" in response["Cache-Control"]
    run = Run.objects.get(pk=data["run_id"])
    assert run.total_items == 1
    polled = api.get(data["links"]["results"])
    assert polled.status_code == 202
    manifest = polled.json()["data"]
    assert manifest["run_id"] == data["run_id"]
    assert manifest["completed"] is False
    assert manifest["counts"]["run_items"]["total"] == 1
    assert "results" not in manifest
    assert set(manifest["links"]) == {
        "results",
        "run",
        "progress",
        "run_items",
        "fields",
        "classifications",
        "segments",
        "cancel",
        "exports",
        "workflow_contract",
    }
    assert polled["ETag"]


def test_existing_documents_and_pending_response(api, dataset, sample_workflow, admin):
    doc = ingestion.ingest_upload(dataset, "sample.txt", upload(), user=admin)
    response = invoke(
        api,
        sample_workflow,
        {"dataset": str(dataset.pk), "document_ids": [str(doc.pk)]},
    )
    assert response.status_code == 202, response.content
    data = response.json()["data"]
    assert data["status"] == "queued"
    assert response["Retry-After"] == "2"
    pending = api.get(data["links"]["results"])
    assert pending.status_code == 202
    assert pending["Retry-After"] == "2"
    Run.objects.filter(pk=data["run_id"]).update(
        status="failed", errors=[{"message": "provider failed"}]
    )
    data = api.get(data["links"]["results"]).json()["data"]
    assert data["completed"] is True and data["status"] == "failed"
    assert data["errors"]["items"] == [
        {"code": "RUN_ERROR", "message": "provider failed", "retryable": None}
    ]


def test_empty_input_rejected_without_run(api, dataset, sample_workflow):
    response = invoke(api, sample_workflow, {"dataset": str(dataset.pk)})
    assert response.status_code == 422
    assert not Run.objects.exists()


def test_foreign_dataset_rejected_before_upload(api, sample_workflow, admin):
    project = Project.available_objects.create(name="Other", slug="other", created_by=admin)
    dataset = Dataset.available_objects.create(project=project, name="Other")
    response = invoke(
        api,
        sample_workflow,
        {"dataset": str(dataset.pk), "files": [upload()]},
        format="multipart",
    )
    assert response.status_code == 404
    assert not Document.objects.exists()


def test_viewer_cannot_invoke_or_read_results(api, dataset, sample_workflow, viewer):
    result = invoke(
        api,
        sample_workflow,
        {"dataset": str(dataset.pk), "files": [upload()]},
        format="multipart",
    ).json()["data"]
    client = APIClient()
    assert client.get(result["links"]["results"]).status_code == 401
    client.force_authenticate(viewer)
    assert client.get(result["links"]["results"]).status_code == 403
    assert (
        client.post(
            invoke_url(sample_workflow), {"dataset": str(dataset.pk)}, format="json"
        ).status_code
        == 403
    )


def test_rejected_upload_does_not_start_partial_run(api, dataset, sample_workflow):
    response = invoke(
        api,
        sample_workflow,
        {
            "dataset": str(dataset.pk),
            "files": [upload(), SimpleUploadedFile("bad.exe", b"not a document")],
        },
        format="multipart",
    )
    assert response.status_code == 422
    assert not Run.objects.exists()


def test_idempotency_key_is_required(api, dataset, sample_workflow):
    response = api.post(
        invoke_url(sample_workflow),
        {"dataset": str(dataset.pk), "files": [upload()]},
        format="multipart",
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert not WorkflowInvocation.objects.exists()


def test_headless_invocation_requires_an_approved_workflow(api, dataset, sample_workflow, admin):
    document = ingestion.ingest_upload(dataset, "sample.txt", upload(), user=admin)
    response = api.post(
        invoke_url(sample_workflow),
        {"dataset": str(dataset.pk), "document_ids": [str(document.pk)]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="draft-workflow",
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "WORKFLOW_NOT_APPROVED"
    assert response.json()["retryable"] is False
    assert not WorkflowInvocation.objects.exists()


def test_identical_upload_retry_replays_run_without_duplicate_work(api, dataset, sample_workflow):
    first = invoke(
        api,
        sample_workflow,
        {"dataset": str(dataset.pk), "files": [upload()]},
        format="multipart",
    )
    second = invoke(
        api,
        sample_workflow,
        {"dataset": str(dataset.pk), "files": [upload()]},
        format="multipart",
    )
    assert second.status_code == first.status_code == 202
    assert second.json()["data"]["run_id"] == first.json()["data"]["run_id"]
    assert second["Idempotency-Replayed"] == "true"
    assert Run.objects.count() == 1
    assert Document.objects.count() == 1
    assert WorkflowInvocation.objects.count() == 1


def test_terminal_retry_still_returns_the_same_async_handle(api, dataset, sample_workflow, admin):
    document = ingestion.ingest_upload(dataset, "sample.txt", upload(), user=admin)
    payload = {
        "dataset": str(dataset.pk),
        "document_ids": [str(document.pk)],
        "client_reference": "source-job-1042",
    }
    first = invoke(api, sample_workflow, payload)
    Run.objects.filter(pk=first.json()["data"]["run_id"]).update(
        status="succeeded", stage="finalized"
    )

    replay = invoke(api, sample_workflow, payload)

    assert replay.status_code == 202
    assert replay["Idempotency-Replayed"] == "true"
    assert replay["Location"] == first["Location"]
    assert replay.json()["data"]["run_id"] == first.json()["data"]["run_id"]
    assert replay.json()["data"]["status"] == "succeeded"


def test_client_reference_is_persisted_filterable_and_part_of_fingerprint(
    api, dataset, sample_workflow, admin
):
    document = ingestion.ingest_upload(dataset, "sample.txt", upload(), user=admin)
    payload = {
        "dataset": str(dataset.pk),
        "document_ids": [str(document.pk)],
        "client_reference": "upstream-case-7",
    }
    accepted = invoke(api, sample_workflow, payload)

    run = Run.objects.get(pk=accepted.json()["data"]["run_id"])
    assert run.client_reference == "upstream-case-7"
    assert accepted.json()["data"]["client_reference"] == "upstream-case-7"
    assert api.get("/api/v1/runs/?client_reference=upstream-case-7").json()["data"]["count"] == 1

    changed = invoke(api, sample_workflow, payload | {"client_reference": "upstream-case-8"})
    assert changed.status_code == 409
    assert changed.json()["error_code"] == "IDEMPOTENCY_KEY_REUSED"


def test_multipart_invocation_reuses_existing_dataset_document(
    api, dataset, sample_workflow, admin
):
    document = ingestion.ingest_upload(dataset, "existing.txt", upload(), user=admin)
    response = invoke(
        api,
        sample_workflow,
        {"dataset": str(dataset.pk), "files": [upload()]},
        key="new-request-for-existing-content",
        format="multipart",
    )

    assert response.status_code == 202
    run = Run.objects.get(pk=response.json()["data"]["run_id"])
    assert list(run.items.values_list("document_id", flat=True)) == [document.pk]
    assert Document.objects.count() == 1


def test_reusing_key_with_different_input_is_a_conflict(api, dataset, sample_workflow, admin):
    first = ingestion.ingest_upload(dataset, "first.txt", upload(), user=admin)
    other_upload = SimpleUploadedFile("other.txt", b"Employee name: Other")
    second = ingestion.ingest_upload(dataset, "other.txt", other_upload, user=admin)
    assert (
        invoke(
            api,
            sample_workflow,
            {"dataset": str(dataset.pk), "document_ids": [str(first.pk)]},
        ).status_code
        == 202
    )
    response = invoke(
        api,
        sample_workflow,
        {"dataset": str(dataset.pk), "document_ids": [str(second.pk)]},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "IDEMPOTENCY_KEY_REUSED"
    assert Run.objects.count() == 1


def test_rejected_upload_retry_replays_failure_without_duplicate_documents(
    api, dataset, sample_workflow
):
    def payload():
        return {
            "dataset": str(dataset.pk),
            "files": [upload(), SimpleUploadedFile("bad.exe", b"not a document")],
        }

    first = invoke(api, sample_workflow, payload(), format="multipart")
    document_count = Document.objects.count()
    second = invoke(api, sample_workflow, payload(), format="multipart")
    assert second.status_code == first.status_code == 422
    assert second.json()["error_code"] == first.json()["error_code"]
    assert second.json()["errors"] == first.json()["errors"]
    assert Document.objects.count() == document_count
    assert WorkflowInvocation.objects.get().status == "failed"


def test_in_progress_invocation_tells_client_to_retry(api, dataset, sample_workflow, admin):
    document = ingestion.ingest_upload(dataset, "sample.txt", upload(), user=admin)
    from docai.api.invocation import _request_hash

    data = {
        "dataset": dataset.pk,
        "document_ids": [document.pk],
        "name": "",
    }
    WorkflowInvocation.objects.create(
        workflow=sample_workflow,
        dataset=dataset,
        key="invocation-1",
        request_hash=_request_hash(data),
        created_by=admin,
        updated_by=admin,
    )
    response = invoke(
        api,
        sample_workflow,
        {"dataset": str(dataset.pk), "document_ids": [str(document.pk)]},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "INVOCATION_IN_PROGRESS"
    assert response.json()["retryable"] is True
    assert response["Retry-After"] == "2"


def test_unexpected_acceptance_failure_is_safely_replayed(
    api, dataset, sample_workflow, admin, monkeypatch
):
    document = ingestion.ingest_upload(dataset, "sample.txt", upload(), user=admin)
    calls = 0

    def fail_run_creation(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("internal detail must not cross the API boundary")

    monkeypatch.setattr("docai.api.invocation.runs.create_run", fail_run_creation)
    payload = {"dataset": str(dataset.pk), "document_ids": [str(document.pk)]}

    first = invoke(api, sample_workflow, payload)
    second = invoke(api, sample_workflow, payload)

    assert first.status_code == second.status_code == 500
    assert first.json()["message"] == second.json()["message"]
    assert "internal detail" not in str(first.json())
    assert calls == 1
    invocation = WorkflowInvocation.objects.get()
    assert invocation.status == "failed"
    assert invocation.failure_code == "INTERNAL_ERROR"


def test_dispatch_failure_is_explicit_and_same_key_retry_redispatches_existing_run(
    api, dataset, sample_workflow, admin, monkeypatch
):
    document = ingestion.ingest_upload(dataset, "sample.txt", upload(), user=admin)
    calls: list[str] = []

    def schedule(run_id):
        calls.append(str(run_id))
        if len(calls) == 1:
            Run.objects.filter(pk=run_id).update(status="running", stage="dispatch_failed")
            raise IntegrationError(
                "Document processing could not be queued.",
                error_code="EXECUTION_QUEUE_UNAVAILABLE",
                headers={"Retry-After": "2"},
            )
        Run.objects.filter(pk=run_id).update(status="running", stage="local_queued")
        return Run.objects.get(pk=run_id)

    monkeypatch.setattr("docai.api.invocation.execution.schedule_run", schedule)
    payload = {"dataset": str(dataset.pk), "document_ids": [str(document.pk)]}

    failed = invoke(api, sample_workflow, payload)
    retried = invoke(api, sample_workflow, payload)

    assert failed.status_code == 503
    assert failed.json()["error_code"] == "EXECUTION_QUEUE_UNAVAILABLE"
    assert failed.json()["retryable"] is True
    assert failed["Retry-After"] == "2"
    assert retried.status_code == 202
    assert retried["Idempotency-Replayed"] == "true"
    assert len(calls) == 2
    assert calls[0] == calls[1] == retried.json()["data"]["run_id"]
    assert Run.objects.count() == 1


def test_expiry_defaults_to_configured_replay_window(
    api, dataset, sample_workflow, admin, settings
):
    settings.DOCAI["IDEMPOTENCY_RETENTION_DAYS"] = 30
    document = ingestion.ingest_upload(dataset, "sample.txt", upload(), user=admin)
    before = timezone.now()
    accepted = invoke(
        api,
        sample_workflow,
        {"dataset": str(dataset.pk), "document_ids": [str(document.pk)]},
    )
    invocation = WorkflowInvocation.objects.get()

    assert before + timedelta(days=29) < invocation.expires_at < before + timedelta(days=31)
    assert accepted.json()["data"]["idempotency_expires_at"].startswith(
        invocation.expires_at.date().isoformat()
    )


def test_cleanup_removes_only_expired_terminal_or_pre_run_failures(
    api, dataset, sample_workflow, admin, capsys
):
    sample_workflow.status = CONFIG_STATUS.approved
    sample_workflow.save(update_fields=["status", "modified"])
    past = timezone.now() - timedelta(days=1)
    future = timezone.now() + timedelta(days=1)

    def run(status, name):
        return Run.objects.create(
            project=sample_workflow.project,
            workflow=sample_workflow,
            dataset=dataset,
            name=name,
            status=status,
            config_snapshot={},
            config_hash=f"sha256:{name}",
            created_by=admin,
        )

    terminal = run("succeeded", "terminal")
    active = run("running", "active")
    retained = run("failed", "retained-window")
    eligible = WorkflowInvocation.objects.create(
        workflow=sample_workflow,
        dataset=dataset,
        key="terminal",
        request_hash="a" * 64,
        status="run_created",
        run=terminal,
        expires_at=past,
        created_by=admin,
    )
    failed_before_run = WorkflowInvocation.objects.create(
        workflow=sample_workflow,
        dataset=dataset,
        key="pre-run-failure",
        request_hash="b" * 64,
        status="failed",
        expires_at=past,
        created_by=admin,
    )
    active_invocation = WorkflowInvocation.objects.create(
        workflow=sample_workflow,
        dataset=dataset,
        key="active",
        request_hash="c" * 64,
        status="run_created",
        run=active,
        expires_at=past,
        created_by=admin,
    )
    future_invocation = WorkflowInvocation.objects.create(
        workflow=sample_workflow,
        dataset=dataset,
        key="future",
        request_hash="d" * 64,
        status="run_created",
        run=retained,
        expires_at=future,
        created_by=admin,
    )

    query_predicate = str(expired_cleanup_queryset().query).lower().split(" where ", 1)[1]
    assert "failure_errors" not in query_predicate
    call_command("cleanup_expired_invocations", dry_run=True)
    assert "2 expired" in capsys.readouterr().out
    call_command("cleanup_expired_invocations")

    assert not WorkflowInvocation.objects.filter(pk=eligible.pk).exists()
    assert not WorkflowInvocation.objects.filter(pk=failed_before_run.pk).exists()
    assert WorkflowInvocation.objects.filter(pk=active_invocation.pk).exists()
    assert WorkflowInvocation.objects.filter(pk=future_invocation.pk).exists()


def test_poll_etag_returns_304_until_manifest_changes(
    api, dataset, sample_workflow, admin, monkeypatch
):
    document = ingestion.ingest_upload(dataset, "sample.txt", upload(), user=admin)
    monkeypatch.setattr(
        "docai.api.invocation.execution.execute_run", lambda pk: Run.objects.get(pk=pk)
    )
    accepted = invoke(
        api,
        sample_workflow,
        {"dataset": str(dataset.pk), "document_ids": [str(document.pk)]},
    )
    results_url = accepted.json()["data"]["links"]["results"]
    first = api.get(results_url)
    unchanged = api.get(results_url, HTTP_IF_NONE_MATCH=f"W/{first['ETag']}")

    assert first.status_code == 202
    assert unchanged.status_code == 304
    assert unchanged.content == b""
    assert unchanged["ETag"] == first["ETag"]
    assert unchanged["Retry-After"] == "2"

    Run.objects.filter(pk=accepted.json()["data"]["run_id"]).update(stage="reading_document")
    changed = api.get(results_url, HTTP_IF_NONE_MATCH=first["ETag"])
    assert changed.status_code == 202
    assert changed["ETag"] != first["ETag"]


def test_poll_notices_are_typed_and_bounded(api, dataset, sample_workflow, admin):
    document = ingestion.ingest_upload(dataset, "sample.txt", upload(), user=admin)
    run = Run.objects.create(
        project=sample_workflow.project,
        workflow=sample_workflow,
        dataset=dataset,
        status="failed",
        config_snapshot={},
        config_hash="sha256:test",
        warnings=[f"warning {index}" for index in range(60)],
        errors=[{"error_code": "UPSTREAM", "message": "failed", "retryable": True}],
        created_by=admin,
    )
    run.items.create(document=document, status="failed", created_by=admin)

    response = api.get(f"/api/v1/runs/{run.pk}/results/")
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["warnings"]["count"] == 60
    assert data["warnings"]["truncated"] is True
    assert len(data["warnings"]["items"]) == 50
    assert data["errors"]["items"] == [{"code": "UPSTREAM", "message": "failed", "retryable": True}]
    assert data["counts"]["run_items"]["failed"] == 1


def test_approved_workflow_contract_exposes_safe_capabilities(
    api, sample_workflow, admin, settings
):
    url = f"/api/v1/workflows/{sample_workflow.pk}/contract/"
    assert api.get(url).status_code == 404

    governance.approve_workflow(sample_workflow, admin)
    response = api.get(url)
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["status"] == "approved"
    assert data["input"]["max_batch_files"] == settings.DOCAI["MAX_BATCH_FILES"]
    assert data["output"]["resources"] == ["segments", "classifications", "fields"]
    assert data["output"]["categories"][0]["key"]
    assert data["output"]["schemas"][0]["fields"]
    assert set(data["links"]) == {"workflow", "invoke"}
    assert "prompt" not in str(data).lower()
    assert "deployment" not in str(data).lower()


def test_headless_get_contracts_have_concrete_openapi_operations(api):
    schema = api.get("/api/schema/").data
    results = schema["paths"]["/api/v1/runs/{run_id}/results/"]["get"]
    contract = schema["paths"]["/api/v1/workflows/{workflow_id}/contract/"]["get"]
    invocation = schema["paths"]["/api/v1/workflows/{workflow_id}/invoke/"]["post"]

    assert results["operationId"] == "headless_run_results_retrieve"
    assert contract["operationId"] == "headless_workflow_contract_retrieve"
    assert invocation["operationId"] == "headless_workflow_invoke"
    assert results["responses"]["200"]["content"]["application/json"]["schema"]["properties"][
        "data"
    ]["$ref"].endswith("/RunResultsManifest")
    assert contract["responses"]["200"]["content"]["application/json"]["schema"]["properties"][
        "data"
    ]["$ref"].endswith("/WorkflowContract")
    assert set(results["responses"]["202"]["headers"]) >= {
        "ETag",
        "Location",
        "Retry-After",
        "X-Request-ID",
    }
    assert "If-None-Match" in {parameter["name"] for parameter in results["parameters"]}
    assert set(invocation["responses"]["202"]["headers"]) >= {
        "Idempotency-Replayed",
        "Location",
        "Retry-After",
        "X-Request-ID",
    }
    error_schema = schema["components"]["schemas"]["ErrorEnvelope"]
    assert error_schema["properties"]["retryable"]["type"] == "boolean"
