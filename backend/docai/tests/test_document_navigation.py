from datetime import timedelta
from uuid import UUID

import pytest
from django.utils import timezone

from docai.models import Dataset, Document, Run, RunItem
from docai.repositories.queries import document_neighbors

pytestmark = pytest.mark.django_db


def make_document(dataset, number):
    return Document.objects.create(
        id=UUID(int=number),
        dataset=dataset,
        original_filename=f"document-{number}.txt",
        sha256=f"{number:064x}",
        file_format="txt",
        mime_type="text/plain",
        size_bytes=1,
        storage_path=f"documents/{number}.txt",
    )


def test_neighbors_cross_pagination_and_resolve_timestamp_ties(
    dataset, django_assert_num_queries, settings
):
    # Like the cache query-budget tests, exclude Silk EXPLAIN queries left by earlier requests.
    if "silk" in settings.INSTALLED_APPS:
        from silk.collector import DataCollector

        DataCollector().clear()
    timestamp = timezone.now()
    docs = [make_document(dataset, number) for number in (1, 2, 3, 4)]
    Document.objects.filter(pk__in=[doc.pk for doc in docs]).update(created=timestamp)
    Document.objects.filter(pk=docs[0].pk).update(created=timestamp + timedelta(days=1))
    Document.objects.filter(pk=docs[-1].pk).update(created=timestamp - timedelta(days=1))
    # More than a client page of documents must not hide the adjacent item.
    extras = Document.objects.bulk_create(
        [
            Document(
                dataset=dataset,
                original_filename=f"extra-{number}.txt",
                sha256=f"{number:064x}",
                file_format="txt",
                size_bytes=1,
                storage_path=f"extra/{number}",
            )
            for number in range(10, 215)
        ]
    )
    Document.objects.filter(pk__in=[doc.pk for doc in extras]).update(
        created=timestamp - timedelta(days=2)
    )
    for index, doc in enumerate(docs):
        doc.refresh_from_db()
        with django_assert_num_queries(2):
            neighbors = document_neighbors(doc)
        if index:
            assert neighbors["previous"]["id"] == docs[index - 1].pk
        else:
            assert neighbors["previous"] is None
        if index < 3:
            assert neighbors["next"]["id"] == docs[index + 1].pk
    assert document_neighbors(docs[1])["scope"] == "dataset"


def test_detail_navigation_stays_in_run_and_dataset(api, dataset, project, sample_workflow):
    docs = [make_document(dataset, number) for number in (1, 2, 3)]
    Document.objects.filter(dataset=dataset).update(created=timezone.now())
    other = Dataset.available_objects.create(project=project, name="Other dataset")
    make_document(other, 4)
    run = Run.objects.create(
        project=project,
        dataset=dataset,
        workflow=sample_workflow,
        config_snapshot={},
        config_hash="sha256:test",
    )
    for doc in (docs[0], docs[2]):
        RunItem.objects.create(run=run, document=doc, idempotency_key=str(doc.pk))
    response = api.get(f"/api/v1/documents/{docs[0].pk}/", {"run": str(run.pk)})
    assert response.status_code == 200
    assert response.json()["data"]["navigation"] == {
        "scope": "run",
        "run": str(run.pk),
        "previous": None,
        "next": {"id": str(docs[2].pk), "original_filename": docs[2].original_filename},
    }
    last = api.get(f"/api/v1/documents/{docs[2].pk}/", {"run": str(run.pk)}).json()["data"][
        "navigation"
    ]
    assert last["previous"]["id"] == str(docs[0].pk)
    assert last["next"] is None
    assert api.get(f"/api/v1/documents/{docs[1].pk}/", {"run": str(run.pk)}).status_code == 404
    assert api.get(f"/api/v1/documents/{docs[0].pk}/", {"run": "invalid"}).status_code == 404
    dataset_nav = api.get(f"/api/v1/documents/{docs[2].pk}/").json()["data"]["navigation"]
    assert dataset_nav["next"] is None
    assert dataset_nav["previous"]["id"] == str(docs[1].pk)


def test_navigation_requires_document_access(api, dataset, monkeypatch):
    doc = make_document(dataset, 1)
    monkeypatch.setattr("docai.api.permissions.can_access_project", lambda user, project: False)
    assert api.get(f"/api/v1/documents/{doc.pk}/").status_code == 403
    api.force_authenticate(user=None)
    assert api.get(f"/api/v1/documents/{doc.pk}/").status_code in (401, 403)
