"""Integration coverage for workflow invocation and inline/polled JSON."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from docai.models import Dataset, Document, Project, Run
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


def test_upload_returns_json_and_poll_matches(api, dataset, sample_workflow):
    response = api.post(
        invoke_url(sample_workflow),
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
    response = api.post(
        invoke_url(sample_workflow),
        {"dataset": str(dataset.pk), "document_ids": [str(doc.pk)]},
        format="json",
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
    response = api.post(invoke_url(sample_workflow), {"dataset": str(dataset.pk)}, format="json")
    assert response.status_code == 422
    assert not Run.objects.exists()


def test_foreign_dataset_rejected_before_upload(api, sample_workflow, admin):
    project = Project.available_objects.create(name="Other", slug="other", created_by=admin)
    dataset = Dataset.available_objects.create(project=project, name="Other")
    response = api.post(
        invoke_url(sample_workflow),
        {"dataset": str(dataset.pk), "files": [upload()]},
        format="multipart",
    )
    assert response.status_code == 404
    assert not Document.objects.exists()


def test_viewer_cannot_invoke_or_read_results(api, dataset, sample_workflow, viewer):
    result = api.post(
        invoke_url(sample_workflow),
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
    response = api.post(
        invoke_url(sample_workflow),
        {
            "dataset": str(dataset.pk),
            "files": [upload(), SimpleUploadedFile("bad.exe", b"not a document")],
        },
        format="multipart",
    )
    assert response.status_code == 422
    assert not Run.objects.exists()
