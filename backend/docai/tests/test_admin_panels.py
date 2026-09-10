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

    celery_response = client.get("/admin/celery/")
    redis_response = client.get("/admin/redis/")

    assert celery_response.status_code == 200
    assert b"Django Celery Panel" in celery_response.content
    assert settings.DJ_CELERY_PANEL_SETTINGS["tasks_backend"].endswith(
        "CeleryTasksInspectBackend"
    )
    assert redis_response.status_code == 200
    assert b"Redis Configuration Required" in redis_response.content


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
        assert client.get(url).status_code == 403


@pytest.mark.django_db
def test_worker_dashboard_describes_the_thread_executor(admin):
    client = Client()
    client.force_login(admin)

    with override_settings(DOCAI={**settings.DOCAI, "TASK_RUNNER": "thread"}):
        response = client.get("/admin/workers/")

    assert response.status_code == 200
    assert b"Thread pool" in response.content
    assert b"In-process executor" in response.content
    assert b"SQLite limits each run to one processing thread" in response.content


@pytest.mark.django_db
def test_worker_dashboard_uses_live_celery_worker_data(admin):
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
    document = ingestion.ingest_upload(
        dataset, w2_pdf.filename, w2_pdf.data, user=admin
    )
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
