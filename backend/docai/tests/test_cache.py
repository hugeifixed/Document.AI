from unittest.mock import Mock

import pytest
from dj_cache_panel.cache_panel import get_cache_panel
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext

from docai.adapters.llm.base import LLMCall, LLMUsage
from docai.models import Dataset, Document, ExtractedField, Project
from docai.schemas.llm import ClassificationOut
from docai.services import llm_usage, run_execution, runs
from docai.services.dashboard import dashboard


@pytest.fixture(autouse=True)
def clear_cache(settings):
    # A profiled API request in another test can leave Silk's collector active.
    # Measure application queries, without inherited EXPLAIN instrumentation.
    if "silk" in settings.INSTALLED_APPS:
        from silk.collector import DataCollector

        DataCollector().clear()
    cache.clear()
    yield
    cache.clear()


def test_locmem_panel_can_list_and_read_application_keys():
    cache.set("docai:smoke", {"ok": True}, 60)
    panel = get_cache_panel("default")

    result = panel.query("default", "docai:*")

    assert result["keys"] == ["docai:smoke"]
    assert panel.get_key("docai:smoke")["value"] == {"ok": True}


@pytest.mark.django_db
def test_cache_panel_is_limited_to_superusers(admin):
    client = Client()
    client.force_login(admin)
    assert client.get("/admin/cache/").status_code == 200

    staff_user = User.objects.create_user("staff", password="pw", is_staff=True)
    client.force_login(staff_user)
    assert client.get("/admin/cache/").status_code == 403


@pytest.mark.django_db
def test_project_dashboard_cache_is_invalidated(project, admin, django_capture_on_commit_callbacks):
    assert dashboard(project.id)["datasets"] == 0

    with django_capture_on_commit_callbacks(execute=True):
        Dataset.available_objects.create(
            project=project,
            name="new dataset",
            split="dev",
            created_by=admin,
        )

    assert dashboard(project.id)["datasets"] == 1


@pytest.fixture
def usage_run(project, dataset, admin, sample_workflow):
    Document.objects.create(
        dataset=dataset,
        original_filename="statement.pdf",
        mime_type="application/pdf",
        file_format="pdf",
        sha256="a" * 64,
        size_bytes=128,
        storage_path="documents/statement.pdf",
        status="validated",
    )
    return runs.create_run(project, sample_workflow, dataset, admin)


def _record_usage(run, *, total=120):
    llm_usage.observer_for(run.items.get())(
        LLMCall(system="", user="", schema=ClassificationOut, stage="classification"),
        LLMUsage(
            provider="azure_openai",
            model_deployment="test",
            input_tokens=total - 20,
            output_tokens=20,
            total_tokens=total,
            finish_reason="stop",
            safety_outcome="clear",
        ),
    )


@pytest.mark.django_db(transaction=True)
def test_dataset_dashboard_reuses_reference_counts_and_keeps_workflow_facts_live(
    usage_run, dataset
):
    run = usage_run
    with CaptureQueriesContext(connection) as cold:
        dashboard(run.project_id, dataset.id)
    with CaptureQueriesContext(connection) as warm:
        dashboard(run.project_id, dataset.id)
    assert len(cold) - len(warm) == 3  # Project, dataset and configuration counts.

    # Bulk updates represent worker writes which cannot invalidate a web LocMem cache.
    type(run).objects.filter(pk=run.pk).update(status="succeeded", processed_items=1)
    field = ExtractedField.objects.create(
        run=run, document=run.items.get().document, name="account", review_status="needs_review"
    )
    for selected in (None, dataset.id):
        data = dashboard(run.project_id, selected)
        assert data["runs"] == {"succeeded": 1}
        assert data["recent_runs"][0]["processed"] == 1
        assert data["review_queue"]["fields"] == 1
    ExtractedField.objects.filter(pk=field.pk).update(review_status="accepted")
    Document.objects.create(
        dataset=dataset,
        original_filename="new.pdf",
        sha256="b" * 64,
        file_format="pdf",
        size_bytes=100,
        status="validated",
    )
    data = dashboard(run.project_id, dataset.id)
    assert data["review_queue"]["fields"] == 0
    assert data["guidance"]["documents"]["new_for_run"] == 1
    assert data["guidance"]["latest_run"]["guidance"]["review"]["fields"] == 0


@pytest.mark.django_db(transaction=True)
def test_reference_counts_are_scoped_and_invalidate_after_catalog_changes(project, dataset, admin):
    assert dashboard(project.id, dataset.id)["datasets"] == 1
    other_project = Project.available_objects.create(name="Other", slug="other", created_by=admin)
    assert dashboard(project.id, dataset.id)["projects"] == 2
    assert dashboard(other_project.id)["datasets"] == 0
    other_dataset = Dataset.available_objects.create(
        project=other_project, name="Other", split="dev"
    )
    assert dashboard(other_project.id, other_dataset.id)["datasets"] == 1
    assert dashboard()["datasets"] == 2
    dataset.delete()
    assert dashboard(project.id)["datasets"] == 0
    assert dashboard(other_project.id)["datasets"] == 1
    assert dashboard()["datasets"] == 1


@pytest.mark.django_db(transaction=True)
def test_rolled_back_reference_counts_are_not_published(project):
    with pytest.raises(ValueError, match="rollback"), transaction.atomic():
        Dataset.available_objects.create(project=project, name="Temporary", split="dev")
        assert dashboard(project.id)["datasets"] == 1
        raise ValueError("rollback")
    assert dashboard(project.id)["datasets"] == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("status", ["running", "succeeded"])
def test_usage_summary_reuses_aggregates_but_detects_new_worker_events(
    usage_run, status, django_assert_num_queries
):
    run = usage_run
    run.status = status
    run.save()
    _record_usage(run)
    with django_assert_num_queries(6):
        initial = llm_usage.summarize_run(run)
    with django_assert_num_queries(1):
        assert llm_usage.summarize_run(run) == initial
    assert initial["total_tokens"] == 120

    # No cache deletion: another process can append a late provider response.
    _record_usage(run, total=240)
    refreshed = llm_usage.summarize_run(run)
    assert refreshed["calls"] == 2
    assert refreshed["total_tokens"] == 360
    assert refreshed["by_stage"][0]["total_tokens"] == 360
    assert refreshed["by_item"][0]["total_tokens"] == 360
    with django_assert_num_queries(1):
        assert llm_usage.summarize_run(run) == refreshed


@pytest.mark.django_db(transaction=True)
def test_retry_refreshes_usage_cache_and_preserves_previous_attempt_tokens(
    usage_run, monkeypatch, django_assert_num_queries
):
    run = usage_run
    run.status = "failed"
    run.save()
    run.items.update(status="failed")
    _record_usage(run)
    assert llm_usage.summarize_run(run)["total_tokens"] == 120
    dispatcher = Mock(is_async=True)
    dispatcher.dispatch.return_value = True
    monkeypatch.setattr(run_execution, "_get_dispatcher", lambda: dispatcher)
    retried = run_execution.execute_run(run.pk, only_failed=True)
    assert retried.status == "running"
    with django_assert_num_queries(6):
        assert llm_usage.summarize_run(retried)["total_tokens"] == 120
    _record_usage(retried, total=240)
    assert llm_usage.summarize_run(retried)["total_tokens"] == 360


@pytest.mark.django_db(transaction=True)
def test_rolled_back_usage_summary_cannot_poison_later_event_count(usage_run):
    # Rollback and replacement produce the same count but different totals.
    with pytest.raises(ValueError, match="rollback"), transaction.atomic():
        _record_usage(usage_run, total=240)
        assert llm_usage.summarize_run(usage_run)["total_tokens"] == 240
        raise ValueError("rollback")
    _record_usage(usage_run, total=120)
    assert llm_usage.summarize_run(usage_run)["total_tokens"] == 120


@pytest.mark.django_db(transaction=True)
def test_warm_usage_cache_still_requires_operator_role(usage_run, operator, viewer):
    from rest_framework.test import APIClient

    _record_usage(usage_run)
    assert llm_usage.summarize_run(usage_run)["total_tokens"] == 120
    client = APIClient()
    client.force_authenticate(viewer)
    url = f"/api/v1/runs/{usage_run.pk}/usage/"
    assert client.get(url).status_code == 403
    client.force_authenticate(operator)
    response = client.get(url)
    assert response.status_code == 200
    assert response.json()["data"]["total_tokens"] == 120
    assert "no-store" in response["Cache-Control"]
    operator.groups.clear()
    client.force_authenticate(type(operator).objects.get(pk=operator.pk))
    assert client.get(url).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_usage_cache_does_not_mix_runs(usage_run, admin):
    other = runs.create_run(usage_run.project, usage_run.workflow, usage_run.dataset, admin)
    _record_usage(usage_run, total=120)
    _record_usage(other, total=480)
    for _ in range(2):
        assert llm_usage.summarize_run(usage_run)["total_tokens"] == 120
        assert llm_usage.summarize_run(other)["total_tokens"] == 480


@pytest.mark.django_db(transaction=True)
def test_summaries_work_with_caching_disabled(usage_run, settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
    assert llm_usage.summarize_run(usage_run)["calls"] == 0
    _record_usage(usage_run)
    assert llm_usage.summarize_run(usage_run)["total_tokens"] == 120
    assert dashboard(usage_run.project_id, usage_run.dataset_id)["datasets"] == 1
