"""Explicit run scope must agree with the picker and never silently widen or shrink."""

from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from docai.models import Dataset, Document, Run

pytestmark = pytest.mark.django_db


def document(dataset, index, status="validated"):
    return Document.objects.create(
        dataset=dataset,
        original_filename=f"statement-{index}.pdf",
        file_format="pdf",
        mime_type="application/pdf",
        sha256=f"{index:064x}",
        size_bytes=128,
        storage_path=f"test/{index}.pdf",
        status=status,
    )


def body(project, dataset, workflow, **scope):
    return {
        "project": str(project.pk),
        "dataset": str(dataset.pk),
        "workflow": str(workflow.pk),
        "execute": False,
        **scope,
    }


def test_picker_filters_and_run_scope_agree(api, project, dataset, sample_workflow):
    allowed = [
        document(dataset, n, status) for n, status in enumerate(Document.RUNNABLE_STATUSES, 1)
    ]
    for n, status in enumerate(["uploaded", "rejected", "processing"], 10):
        document(dataset, n, status)
    other = Dataset.objects.create(project=project, name="Other collection")
    document(other, 20)
    response = api.get(
        "/api/v1/documents/",
        {"dataset": str(dataset.pk), "runnable": "true", "ordering": "created"},
    )
    assert response.status_code == 200
    assert {row["id"] for row in response.json()["data"]["results"]} == {
        str(doc.pk) for doc in allowed
    }
    chosen = [str(allowed[0].pk), str(allowed[2].pk)]
    response = api.post(
        "/api/v1/runs/", body(project, dataset, sample_workflow, document_ids=chosen), format="json"
    )
    assert response.status_code == 201
    run = Run.objects.get(pk=response.json()["data"]["id"])
    assert set(run.items.values_list("document_id", flat=True)) == {allowed[0].pk, allowed[2].pk}
    assert run.config_snapshot["document_ids"] == chosen
    assert run.total_items == 2
    assert run.sample_size is None


@pytest.mark.parametrize(
    "invalid", ["outside_dataset", "deleted", "processing", "rejected", "missing"]
)
def test_unavailable_selection_rejects_the_whole_request(
    api, project, dataset, sample_workflow, invalid
):
    good = document(dataset, 1)
    stale = document(dataset, 2)
    stale_id = stale.pk
    if invalid == "outside_dataset":
        other = Dataset.objects.create(project=project, name="Other collection")
        Document.objects.filter(pk=stale.pk).update(dataset=other)
    elif invalid == "deleted":
        stale.delete()
    elif invalid == "missing":
        stale_id = uuid4()
    else:
        Document.objects.filter(pk=stale.pk).update(status=invalid)
    before = Run.objects.count()
    response = api.post(
        "/api/v1/runs/",
        body(project, dataset, sample_workflow, document_ids=[str(good.pk), str(stale_id)]),
        format="json",
    )
    assert response.status_code == 422
    assert any(error["field"] == "document_ids" for error in response.json()["errors"])
    assert Run.objects.count() == before


@pytest.mark.parametrize(
    "scope", [{"document_ids": []}, {"sample_size": 1, "document_ids": [str(uuid4())]}]
)
def test_empty_or_ambiguous_selection_never_runs_the_dataset(
    api, project, dataset, sample_workflow, scope
):
    document(dataset, 1)
    response = api.post(
        "/api/v1/runs/", body(project, dataset, sample_workflow, **scope), format="json"
    )
    assert response.status_code == 422
    assert not Run.objects.exists()


def test_limit_is_oldest_first_with_stable_ties_and_skips_ineligible(
    api, project, dataset, sample_workflow
):
    document(dataset, 0, "rejected")
    allowed = [document(dataset, n) for n in (1, 2, 3)]
    Document.objects.filter(pk__in=[doc.pk for doc in allowed]).update(created=allowed[0].created)
    response = api.post(
        "/api/v1/runs/", body(project, dataset, sample_workflow, sample_size=2), format="json"
    )
    assert response.status_code == 201
    run = Run.objects.get(pk=response.json()["data"]["id"])
    assert set(run.items.values_list("document_id", flat=True)) == set(
        sorted(doc.pk for doc in allowed)[:2]
    )


def test_manual_selection_does_not_bypass_operator_role(
    project, dataset, sample_workflow, reviewer
):
    selected = document(dataset, 1)
    client = APIClient()
    client.force_authenticate(reviewer)
    response = client.post(
        "/api/v1/runs/",
        body(project, dataset, sample_workflow, document_ids=[str(selected.pk)]),
        format="json",
    )
    assert response.status_code == 403
    assert not Run.objects.exists()
