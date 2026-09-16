import pytest
from django.apps import apps
from django.db import connection, models
from django.test.utils import CaptureQueriesContext
from drf_spectacular.validation import validate_schema

from docai.exceptions import WorkflowConfigError
from docai.models import AuditEvent, Dataset, Project
from docai.services import governance

pytestmark = pytest.mark.django_db


def _details(response):
    return {detail["field"]: detail for detail in response.json()["errors"]}


def test_uuid_pks_and_audit_fields(project):
    assert (
        len(str(project.id)) == 36 and project.created and project.modified and project.created_by
    )


def test_oracle_lob_fields_are_not_used_in_indexes_constraints_or_default_ordering():
    violations = []
    lob_types = (models.BinaryField, models.JSONField, models.TextField)
    for model in apps.get_app_config("docai").get_models():
        lob_fields = {field.name for field in model._meta.fields if isinstance(field, lob_types)}
        for field in model._meta.fields:
            if field.name in lob_fields and (
                getattr(field, "db_index", False) or field.unique or field.primary_key
            ):
                violations.append(f"{model.__name__}.{field.name}: field index")
        for index in model._meta.indexes:
            if indexed := lob_fields.intersection(index.fields):
                violations.append(f"{model.__name__}.{sorted(indexed)}: {index.name}")
        for constraint in model._meta.constraints:
            constrained = lob_fields.intersection(getattr(constraint, "fields", ()) or ())
            if constrained:
                violations.append(f"{model.__name__}.{sorted(constrained)}: {constraint.name}")
        ordered = lob_fields.intersection(
            field.removeprefix("-")
            for field in model._meta.ordering or ()
            if isinstance(field, str)
        )
        if ordered:
            violations.append(f"{model.__name__}.{sorted(ordered)}: default ordering")

    assert violations == []


def test_governance_service_allocates_and_audits_model_and_template_versions(project, admin):
    first_model = governance.create_model_version(
        name="invoice-model",
        adapter="mock",
        deployment="fixture-v1",
        parameters={"temperature": 0},
        user=admin,
    )
    with CaptureQueriesContext(connection) as captured:
        second_model = governance.create_model_version(
            name="invoice-model",
            adapter="mock",
            deployment="fixture-v2",
            user=admin,
        )
    schema = governance.new_schema_version(
        "invoice", [{"name": "total", "type": "currency"}], admin
    )
    prompt = governance.new_prompt_version(
        "invoice-extract", "extraction", "Extract invoice fields.", "{document}", admin
    )
    first_template = governance.create_template_version(
        project=project,
        name="invoice",
        document_type="invoice",
        schema_version=schema,
        prompt_version=prompt,
        model_config=second_model,
        user=admin,
    )
    second_template = governance.create_template_version(
        project=project,
        name="invoice",
        document_type="invoice",
        schema_version=schema,
        prompt_version=prompt,
        model_config=second_model,
        user=admin,
    )

    assert (first_model.version, second_model.version) == (1, 2)
    version_reads = [
        query["sql"].upper()
        for query in captured.captured_queries
        if "SELECT" in query["sql"].upper() and "DOCAI_MODEL_CONFIGURATION" in query["sql"].upper()
    ]
    assert version_reads
    assert all(" LIMIT " not in sql and " FETCH FIRST " not in sql for sql in version_reads)
    assert (first_template.version, second_template.version) == (1, 2)
    assert set(
        AuditEvent.objects.filter(
            object_id__in=[str(second_model.id), str(second_template.id)]
        ).values_list("action", flat=True)
    ) == {"model.version_created", "template.version_created"}


def test_soft_deleted_catalog_rows_require_explicit_all_objects_access(project, dataset):
    dataset.delete()
    project.delete()

    assert not Dataset.available_objects.filter(pk=dataset.pk).exists()
    assert not Project.available_objects.filter(pk=project.pk).exists()
    assert Dataset.all_objects.get(pk=dataset.pk).is_removed is True
    assert Project.all_objects.get(pk=project.pk).is_removed is True
    assert Project.objects.filter(pk=project.pk).exists()
    assert not project.datasets.filter(pk=dataset.pk).exists()
    assert Project._default_manager.name == "available_objects"
    assert Project._base_manager.name == "all_objects"


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
    assert (
        body["success"] is False
        and body["error_code"] == "VALIDATION_ERROR"
        and _details(r)["name"]["code"] == "required"
        and body["trace_id"]
    )


def test_schema_validation_error_is_not_treated_as_an_internal_failure(api):
    response = api.post(
        "/api/v1/schemas/",
        {
            "name": "invalid-schema",
            "field_definitions": [{"name": "amount", "type": "not-a-field-type"}],
        },
        format="json",
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


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
    assert _details(duplicate)["slug"] == {
        "field": "slug",
        "message": "A project with this slug already exists.",
        "code": "invalid",
    }


def test_not_found_is_404_envelope(api):
    r = api.get("/api/v1/projects/00000000-0000-0000-0000-000000000000/")
    assert r.status_code == 404 and r.json()["error_code"] == "NOT_FOUND"


def test_api_root_redirects_to_interactive_documentation(client):
    response = client.get("/api/")

    assert response.status_code == 302
    assert response.url == "/api/docs/"


def test_unknown_local_api_route_suggests_docs_and_profiler(api, settings):
    settings.DEBUG = True
    settings.SILKY_ENABLED = True

    response = api.get("/api/silk")

    assert response.status_code == 404
    detail = _details(response)["detail"]["message"]
    assert "/api/" in detail
    assert "/admin/profiler/" in detail


def test_unknown_api_route_keeps_production_response_generic(api, settings):
    settings.DEBUG = False

    response = api.get("/api/no-such-route")

    assert response.status_code == 404
    assert _details(response)["detail"]["message"] == "No API route matches this URL."


def test_unauthenticated_is_401_with_challenge():
    from rest_framework.test import APIClient

    r = APIClient().get("/api/v1/projects/")
    assert r.status_code == 401 and r.json()["success"] is False
    assert r["WWW-Authenticate"] == 'Session realm="api"'


def test_viewer_cannot_write(viewer, project):
    from rest_framework.test import APIClient

    c = APIClient()
    c.force_authenticate(viewer)
    assert c.get("/api/v1/projects/").status_code == 200
    r = c.post("/api/v1/projects/", {"name": "x", "slug": "x"}, format="json")
    assert r.status_code == 403 and r.json()["error_code"] == "PERMISSION_DENIED"


def test_workflow_config_validated_and_versioned(project, admin):
    cfg = {
        "categories": [{"key": "w2", "name": "W-2", "extraction_schema": "w2"}],
        "schemas": [{"name": "w2", "fields": [{"name": "ssn", "type": "identifier"}]}],
    }
    wf1 = governance.create_workflow_version(project, "wf", "unbundle_classify_extract", cfg, admin)
    wf2 = governance.create_workflow_version(project, "wf", "unbundle_classify_extract", cfg, admin)
    assert (wf1.version, wf2.version) == (1, 2) and wf1.content_hash == wf2.content_hash
    with pytest.raises(WorkflowConfigError):
        governance.create_workflow_version(
            project,
            "bad",
            "unbundle_classify_extract",
            {"categories": [{"key": "w2", "name": "W-2", "extraction_schema": "missing"}]},
            admin,
        )


def test_approval_requires_role_and_is_audited(project, admin, operator, sample_workflow):
    from docai.exceptions import PermissionDenied
    from docai.models import AuditEvent

    with pytest.raises(PermissionDenied):
        governance.approve_workflow(sample_workflow, operator)
    governance.approve_workflow(sample_workflow, admin, "looks good")
    sample_workflow.refresh_from_db()
    assert sample_workflow.status == "approved" and sample_workflow.approved_by == admin
    assert AuditEvent.objects.filter(
        action="workflow.approved", object_id=str(sample_workflow.id)
    ).exists()


def test_workflow_types_endpoint_exposes_json_schemas(api):
    r = api.get("/api/v1/workflows/types/")
    assert r.status_code == 200 and "unbundle_classify_extract" in r.json()["data"]
    assert "properties" in r.json()["data"]["extract_unstructured"]["schema"]


def test_openapi_schema_generates(api):
    r = api.get("/api/schema/")
    assert r.status_code == 200
    schema = r.data
    assert schema["openapi"] == "3.2.0"
    validate_schema(schema)
    assert schema["info"]["title"] == "DocAI Platform API"
    assert [tag["name"] for tag in schema["tags"]] == [
        "Authentication",
        "Workspace",
        "Configuration",
        "Processing",
        "Review & labeling",
        "Evaluation & export",
        "Operations & audit",
        "Metrics",
        "Headless integration",
    ]

    projects = schema["paths"]["/api/v1/projects/"]["get"]
    assert projects["summary"] == "List projects"
    assert projects["tags"] == ["Workspace"]
    success_schema = projects["responses"]["200"]["content"]["application/json"]["schema"]
    assert success_schema["properties"]["data"]["$ref"].endswith("/PaginatedProjectList")
    assert projects["responses"]["default"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ErrorEnvelope")
    assert "X-Request-ID" in projects["responses"]["200"]["headers"]

    for path in schema["paths"].values():
        for operation in path.values():
            if isinstance(operation, dict) and "201" in operation.get("responses", {}):
                assert "Location" in operation["responses"]["201"]["headers"]

    run_create = schema["paths"]["/api/v1/runs/"]["post"]
    request_ref = run_create["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert request_ref.endswith("/RunCreateRequest")
    assert run_create["x-required-role"] == "operator"
    assert "Location" in run_create["responses"]["202"]["headers"]

    category_detail = schema["paths"]["/api/v1/categories/{id}/"]
    assert "patch" not in category_detail and "put" not in category_detail
    promote = schema["paths"]["/api/v1/fields/{id}/promote/"]["post"]
    assert promote["x-required-role"] == "approver"

    run_export = schema["paths"]["/api/v1/runs/{id}/export/{fmt}/"]["get"]
    assert run_export["tags"] == ["Evaluation & export"]
    assert set(run_export["responses"]["200"]["content"]) == {
        "application/json",
        "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    assert schema["paths"]["/api/v1/runs/{id}/usage/"]["get"]["x-required-role"] == "operator"


@pytest.mark.parametrize("deployment", ["institution-gpt52", "gpt-5.2"])
def test_workflow_capabilities_expose_only_the_effective_model_default(api, settings, deployment):
    settings.DOCAI = {
        **settings.DOCAI,
        "AZURE_OPENAI_DEPLOYMENT": deployment,
        "AZURE_OPENAI_API_KEY": "must-not-be-exposed",
    }
    response = api.get("/api/v1/workflows/capabilities/")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["defaults"] == {"azure_openai_deployment": deployment}
    assert set(data) == {"defaults", "image_normalization", "di_analysis"}
    assert "must-not-be-exposed" not in response.content.decode()


def test_new_model_and_sample_workflow_defaults_use_the_expected_deployment(settings):
    from docai.management.commands.seed_defaults import sample_workflow_configs
    from docai.schemas.config import ModelSettings

    assert ModelSettings().deployment == "gpt-5.2"
    settings.DOCAI = {**settings.DOCAI, "AZURE_OPENAI_DEPLOYMENT": "institution-gpt52"}
    for _, config in sample_workflow_configs().values():
        if "model" in config:
            assert config["model"]["deployment"] == "institution-gpt52"
