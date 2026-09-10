import pytest

from docai.services import governance

pytestmark = pytest.mark.django_db


def test_uuid_pks_and_audit_fields(project):
    assert len(str(project.id)) == 36 and project.created and project.modified and project.created_by


def test_success_envelope_and_trace_id(api, project):
    r = api.get("/api/v1/projects/")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and "trace_id" in body and body["data"]["count"] == 1
    assert set(body["data"]) >= {"count", "page", "page_size", "total_pages", "results"}
    assert r["X-Request-ID"]


def test_validation_error_is_422_with_code(api):
    r = api.post("/api/v1/projects/", {"description": "no name"}, format="json")
    assert r.status_code == 422
    body = r.json()
    assert body["success"] is False and body["error_code"] == "VALIDATION_ERROR" and "name" in body["errors"] and body["trace_id"]


def test_project_slug_is_generated_or_can_be_customized(api):
    generated = api.post(
        "/api/v1/projects/",
        {"name": "Commercial Loan Onboarding"},
        format="json",
    )
    assert generated.status_code == 201
    assert generated.json()["data"]["slug"] == "commercial-loan-onboarding"

    customized = api.post(
        "/api/v1/projects/",
        {"name": "Accounts Receivable", "slug": "ar-intake"},
        format="json",
    )
    assert customized.status_code == 201
    assert customized.json()["data"]["slug"] == "ar-intake"


def test_generated_project_slug_collision_is_a_validation_error(api):
    first = api.post("/api/v1/projects/", {"name": "Same Name"}, format="json")
    duplicate = api.post("/api/v1/projects/", {"name": "Same Name"}, format="json")

    assert first.status_code == 201
    assert duplicate.status_code == 422
    assert duplicate.json()["errors"]["slug"] == ["A project with this slug already exists."]


def test_not_found_is_404_envelope(api):
    r = api.get("/api/v1/projects/00000000-0000-0000-0000-000000000000/")
    assert r.status_code == 404 and r.json()["error_code"] == "NOT_FOUND"


def test_unauthenticated_is_401_or_403():
    from rest_framework.test import APIClient
    r = APIClient().get("/api/v1/projects/")
    assert r.status_code in (401, 403) and r.json()["success"] is False


def test_viewer_cannot_write(viewer, project):
    from rest_framework.test import APIClient
    c = APIClient(); c.force_authenticate(viewer)
    assert c.get("/api/v1/projects/").status_code == 200
    r = c.post("/api/v1/projects/", {"name": "x", "slug": "x"}, format="json")
    assert r.status_code == 403 and r.json()["error_code"] == "PERMISSION_DENIED"


def test_workflow_config_validated_and_versioned(project, admin):
    cfg = {"categories": [{"key": "w2", "name": "W-2", "extraction_schema": "w2"}],
           "schemas": [{"name": "w2", "fields": [{"name": "ssn", "type": "identifier"}]}]}
    wf1 = governance.create_workflow_version(project, "wf", "unbundle_classify_extract", cfg, admin)
    wf2 = governance.create_workflow_version(project, "wf", "unbundle_classify_extract", cfg, admin)
    assert (wf1.version, wf2.version) == (1, 2) and wf1.content_hash == wf2.content_hash
    with pytest.raises(Exception):
        governance.create_workflow_version(project, "bad", "unbundle_classify_extract",
                                           {"categories": [{"key": "w2", "name": "W-2", "extraction_schema": "missing"}]}, admin)


def test_approval_requires_role_and_is_audited(project, admin, operator, sample_workflow):
    from docai.exceptions import PermissionDenied
    from docai.models import AuditEvent
    with pytest.raises(PermissionDenied):
        governance.approve_workflow(sample_workflow, operator)
    governance.approve_workflow(sample_workflow, admin, "looks good")
    sample_workflow.refresh_from_db()
    assert sample_workflow.status == "approved" and sample_workflow.approved_by == admin
    assert AuditEvent.objects.filter(action="workflow.approved", object_id=str(sample_workflow.id)).exists()


def test_workflow_types_endpoint_exposes_json_schemas(api):
    r = api.get("/api/v1/workflows/types/")
    assert r.status_code == 200 and "unbundle_classify_extract" in r.json()["data"]
    assert "properties" in r.json()["data"]["extract_unstructured"]["schema"]


def test_openapi_schema_generates(api):
    r = api.get("/api/schema/")
    assert r.status_code == 200
    schema = r.data
    assert schema["info"]["title"] == "DocAI Platform API"
    assert [tag["name"] for tag in schema["tags"]] == [
        "Authentication",
        "Workspace",
        "Configuration",
        "Processing",
        "Review & labeling",
        "Evaluation & export",
        "Operations & audit",
    ]

    projects = schema["paths"]["/api/v1/projects/"]["get"]
    assert projects["summary"] == "List projects"
    assert projects["tags"] == ["Workspace"]
    success_schema = projects["responses"]["200"]["content"]["application/json"]["schema"]
    assert success_schema["properties"]["data"]["$ref"].endswith("/PaginatedProjectList")
    assert projects["responses"]["default"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ErrorEnvelope"
    )
    assert "X-Request-ID" in projects["responses"]["200"]["headers"]

    run_create = schema["paths"]["/api/v1/runs/"]["post"]
    request_ref = run_create["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert request_ref.endswith("/RunCreateRequest")
    assert run_create["x-required-role"] == "operator"

    run_export = schema["paths"]["/api/v1/runs/{id}/export/{fmt}/"]["get"]
    assert run_export["tags"] == ["Evaluation & export"]
    assert set(run_export["responses"]["200"]["content"]) == {
        "application/json",
        "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
