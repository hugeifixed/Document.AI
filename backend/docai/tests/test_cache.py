import pytest
from dj_cache_panel.cache_panel import get_cache_panel
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client

from docai.models import Dataset
from docai.services.dashboard import dashboard


@pytest.fixture(autouse=True)
def clear_cache():
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
def test_project_dashboard_cache_is_invalidated(
    project, admin, django_capture_on_commit_callbacks
):
    assert dashboard(project.id)["datasets"] == 0

    with django_capture_on_commit_callbacks(execute=True):
        Dataset.objects.create(
            project=project,
            name="new dataset",
            split="dev",
            created_by=admin,
        )

    assert dashboard(project.id)["datasets"] == 1
