import warnings

import pytest
from django.core.paginator import UnorderedObjectListWarning
from django.db.models import Count
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from docai.api.pagination import StableOrderingFilter
from docai.models import Dataset, Project

pytestmark = pytest.mark.django_db


def test_dataset_pages_are_ordered_and_use_a_unique_tie_breaker(api, admin):
    projects = [
        Project.objects.create(name="Project", slug=f"project-{index}", created_by=admin)
        for index in range(2)
    ]
    datasets = [
        Dataset.objects.create(project=project, name="Shared name", created_by=admin)
        for project in projects
    ]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", UnorderedObjectListWarning)
        pages = [
            api.get("/api/v1/datasets/", {"ordering": "name", "page_size": 1, "page": page})
            for page in (1, 2)
        ]

    assert all(response.status_code == 200 for response in pages)
    assert not [warning for warning in caught if warning.category is UnorderedObjectListWarning]
    actual_ids = [response.json()["data"]["results"][0]["id"] for response in pages]
    assert actual_ids == sorted(str(dataset.id) for dataset in datasets)


def test_stable_ordering_filter_appends_primary_key():
    request = Request(APIRequestFactory().get("/", {"ordering": "name"}))
    view = type("View", (), {"ordering": ["name"], "ordering_fields": ["name"]})()
    queryset = Dataset.objects.annotate(document_count=Count("documents"))

    ordered = StableOrderingFilter().filter_queryset(request, queryset, view)

    assert ordered.ordered
    assert ordered.query.order_by == ("name", "id")
