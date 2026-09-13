from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client
from django.test.utils import override_settings

from docai.models import ITEM_STATUS
from docai.services import ingestion
from docai.services import runs as run_service


@pytest.mark.django_db
def test_optional_operational_panels_are_safe_without_services(admin):
    client = Client()
    client.force_login(admin)

    if "dj_celery_panel" not in settings.INSTALLED_APPS:
        pytest.skip("Optional Celery panel is not installed")
    celery_response = client.get("/admin/celery/")
    redis_response = client.get("/admin/redis/")

    assert celery_response.status_code == 200
    assert b"Django Celery Panel" in celery_response.content
    assert str(settings.DJ_CELERY_PANEL_SETTINGS["tasks_backend"]).endswith(
        "CeleryTasksInspectBackend"
    )
    if "dj_redis_panel" in settings.INSTALLED_APPS:
        assert redis_response.status_code == 200
        assert b"Redis Configuration Required" in redis_response.content
    else:
        assert redis_response.status_code == 404


@pytest.mark.django_db
def test_operational_panels_are_limited_to_superusers():
    staff = User.objects.create_user("staff", password="pw", is_staff=True)
    client = Client()
    client.force_login(staff)

    for url in (
        "/admin/celery/",
        "/admin/redis/",
        "/admin/errors/",
        "/admin/workers/",
    ):
        optional = {"/admin/celery/": "dj_celery_panel", "/admin/redis/": "dj_redis_panel"}
        installed = url not in optional or optional[url] in settings.INSTALLED_APPS
        assert client.get(url).status_code == (403 if installed else 404)


@pytest.mark.django_db
def test_worker_dashboard_describes_the_thread_executor(admin):
    client = Client()
    client.force_login(admin)

    with override_settings(DOCAI={**settings.DOCAI, "TASK_RUNNER": "thread"}):
        response = client.get("/admin/workers/")

    assert response.status_code == 200
    assert b"Thread runner" in response.content
    assert b"SQLite runs document work sequentially on the requesting thread" in response.content
    assert b"Inline SQLite executor" in response.content


@pytest.mark.django_db
def test_worker_dashboard_uses_live_celery_worker_data(admin):
    pytest.importorskip("dj_celery_panel")
    client = Client()
    client.force_login(admin)
    celery_settings = {**settings.DOCAI, "TASK_RUNNER": "celery"}
    worker = {
        "name": "celery@worker-1",
        "status": "online",
        "pool": "prefork",
        "concurrency": 4,
        "total_tasks_executed": 12,
        "pid": 321,
    }

    with (
        override_settings(
            DOCAI=celery_settings,
            CELERY_BROKER_URL="filesystem://",
            CELERY_WORKER_CONCURRENCY=4,
        ),
        patch("docai.admin_panels._inspect_celery_workers", return_value=([worker], "")),
    ):
        response = client.get("/admin/workers/")

    assert response.status_code == 200
    assert b"celery@worker-1" in response.content
    assert b"prefork" in response.content
    assert b"1 ONLINE" in response.content


@pytest.mark.django_db
def test_processing_error_panel_groups_and_links_current_failures(
    admin, dataset, project, sample_workflow, w2_pdf
):
    document = ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_service.create_run(project, sample_workflow, dataset, admin, name="Failed run")
    item = run.items.get(document=document)
    item.status = ITEM_STATUS.failed
    item.error_code = "AZURE_TIMEOUT"
    item.error_message = "The document analysis service timed out."
    item.retryable = True
    item.attempts = 2
    item.save(
        update_fields=[
            "status",
            "error_code",
            "error_message",
            "retryable",
            "attempts",
            "modified",
        ]
    )

    client = Client()
    client.force_login(admin)
    response = client.get("/admin/errors/")

    assert response.status_code == 200
    assert b"AZURE_TIMEOUT" in response.content
    assert b"The document analysis service timed out." in response.content
    assert str(item.pk).encode() in response.content

    no_match = client.get("/admin/errors/", {"q": "different error"})
    assert b"No matching processing errors" in no_match.content


@pytest.mark.django_db
def test_solo_inspection_silence_keeps_database_activity_visible(
    admin, dataset, project, sample_workflow, w2_pdf
):
    document = ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_service.create_run(project, sample_workflow, dataset, admin)
    run.items.update(status=ITEM_STATUS.running, stage="workflow")
    client = Client()
    client.force_login(admin)
    with (
        override_settings(
            DOCAI={**settings.DOCAI, "TASK_RUNNER": "celery"},
            CELERY_WORKER_POOL="solo",
            CELERY_WORKER_CONCURRENCY=8,
        ),
        patch("docai.admin_panels._inspect_celery_workers", return_value=([], "No reply")),
    ):
        response = client.get("/admin/workers/")
    assert response.status_code == 200
    assert response.context["activity_counts"]["running"] == 1
    assert response.context["configured_capacity"] == 1
    assert b"NO REPLY" in response.content and b"NO WORKERS" not in response.content
    assert b"Solo worker: one document at a time" in response.content
    assert document.original_filename.encode() in response.content


@pytest.mark.django_db
def test_celery_panel_explains_solo_inspection_without_contacting_broker(admin):
    if "dj_celery_panel" not in settings.INSTALLED_APPS:
        pytest.skip("Optional Celery panel is not installed")
    client = Client()
    client.force_login(admin)
    with patch("celery.app.control.Control.inspect", side_effect=AssertionError("broker call")):
        response = client.get("/admin/celery/")
    assert response.status_code == 200
    assert b"A busy solo worker cannot answer inspection" in response.content
    assert b'href="/admin/workers/"' in response.content


def test_no_reply_is_not_reported_as_a_stopped_worker():
    pytest.importorskip("dj_celery_panel")
    from dj_celery_panel.celery_utils.workers import WorkerListPage

    from docai.admin_panels import _inspect_celery_workers

    with patch(
        "dj_celery_panel.celery_utils.CeleryWorkersInspectBackend.get_workers",
        return_value=WorkerListPage([], [], 0, False, "No workers are currently running"),
    ):
        workers, error = _inspect_celery_workers()
    assert workers == []
    assert "No worker replied" in error


@pytest.mark.django_db
def test_celery_worker_tab_does_not_claim_silent_workers_are_stopped(admin):
    pytest.importorskip("dj_celery_panel")
    client = Client()
    client.force_login(admin)
    with patch("celery.app.control.Inspect.stats", return_value=None):
        response = client.get("/admin/celery/workers/")
    assert response.status_code == 200
    assert b"No worker replies received" in response.content
    assert b"No Workers Running" not in response.content
    assert b"No workers are currently running" not in response.content
