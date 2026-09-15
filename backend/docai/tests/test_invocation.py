"""Integration coverage for workflow invocation and inline/polled JSON."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from docai.models import Dataset, Document, Project, Run, WorkflowInvocation
from docai.services import ingestion

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.DOCAI_DATA_DIR = tmp_path


def invoke_url(workflow):
    return f"/api/v1/workflows/{workflow.pk}/invoke/"


def upload():
    return SimpleUploadedFile("sample.txt", b"Employee name: Alex Sample\nWages: 1000")


def invoke(api, workflow, data, *, key="invocation-1", format="json"):
    return api.post(
        invoke_url(workflow),
        data,
        format=format,
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_upload_returns_json_and_poll_matches(api, dataset, sample_workflow):
    response = invoke(
        api,
        sample_workflow,
        {"dataset": str(dataset.pk), "files": [upload()]},
        format="multipart",
    )
    assert response.status_code == 200, response.content
    data = response.json()["data"]
    assert data["completed"] is True
    assert data["workflow"]["version"] == sample_workflow.version
    assert set(data["results"]) == {"fields", "classifications", "segments", "errors"}
    assert "no-store" in response["Cache-Control"]
    run = Run.objects.get(pk=data["run_id"])
    assert run.total_items == 1
    polled = api.get(data["results_url"])
    assert polled.status_code == 200
    assert polled.json()["data"] == data


def test_existing_documents_and_pending_response(api, dataset, sample_workflow, admin, monkeypatch):
    doc = ingestion.ingest_upload(dataset, "sample.txt", upload(), user=admin)
    monkeypatch.setattr(
        "docai.api.invocation.execution.execute_run", lambda pk: Run.objects.get(pk=pk)
    )
    response = invoke(
        api,
        sample_workflow,
        {"dataset": str(dataset.pk), "document_ids": [str(doc.pk)]},
    )
    assert response.status_code == 202, response.content
    data = response.json()["data"]
    assert data["completed"] is False and data["results"] is None
    assert response["Retry-After"] == "2"
    assert api.get(data["results_url"]).status_code == 202
    Run.objects.filter(pk=data["run_id"]).update(
        status="failed", errors=[{"message": "provider failed"}]
    )
    data = api.get(data["results_url"]).json()["data"]
    assert data["completed"] is True and data["status"] == "failed"
    assert data["errors"] == [{"message": "provider failed"}]


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
    assert client.get(result["results_url"]).status_code == 401
    client.force_authenticate(viewer)
    assert client.get(result["results_url"]).status_code == 403
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
    assert second.status_code == first.status_code == 200
    assert second.json()["data"]["run_id"] == first.json()["data"]["run_id"]
    assert Run.objects.count() == 1
    assert Document.objects.count() == 1
    assert WorkflowInvocation.objects.count() == 1


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
        == 200
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
