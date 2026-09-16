from __future__ import annotations

import uuid

import pytest
from django.conf import settings
from rest_framework.exceptions import Throttled

from docai.adapters.llm.base import LLMCall, LLMUsage
from docai.api.exception_handler import docai_exception_handler
from docai.models import (
    CategoryDefinition,
    ClassificationResult,
    Dataset,
    Document,
    ExtractedField,
    GroundTruthLabel,
    LLMUsageEvent,
    Segment,
    WorkflowConfiguration,
)
from docai.schemas.llm import ClassificationOut
from docai.services import evaluation as evaluation_service
from docai.services import governance, llm_usage
from docai.services import run_execution as execution_service
from docai.services import runs as run_service
from docai.views import CORE_HEALTH_CHECKS, SystemHealthView

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("endpoint", ["/workflows/validate/", "/workflows/"])
def test_workflow_errors_include_every_field_without_raw_inputs(api, project, endpoint):
    names = ["box9", "box12_items", "box14a_other_items", "occupation_codes", "state_local_items"]
    response = api.post(
        f"/api/v1{endpoint}",
        {
            **(
                {"project": str(project.pk), "name": "W2 validation"}
                if endpoint == "/workflows/"
                else {}
            ),
            "workflow_type": "unbundle_classify_extract",
            "config": {
                "categories": [{"key": "w2", "name": "W2", "extraction_schema": "w2"}],
                "schemas": [
                    {
                        "name": "w2",
                        "fields": [
                            {
                                "name": name,
                                "type": "reserved" if i == 0 else "array",
                                "guidance": "private-input-marker",
                            }
                            for i, name in enumerate(names)
                        ],
                    }
                ],
            },
        },
        format="json",
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["error_code"] == (
        "VALIDATION_ERROR" if endpoint == "/workflows/validate/" else "WORKFLOW_CONFIG_ERROR"
    )
    assert [detail["field"] for detail in payload["errors"]] == [
        f"config.schemas.0.fields.{i}.type" for i in range(5)
    ]
    assert all("'list'" in detail["message"] for detail in payload["errors"])
    assert "private-input-marker" not in str(payload)
    assert "errors.pydantic.dev" not in str(payload)
    assert "input_value" not in str(payload)
    assert not WorkflowConfiguration.objects.filter(name="W2 validation").exists()


def _details(response):
    return {detail["field"]: detail for detail in response.json()["errors"]}


def _document(dataset, *, digest: str = "a" * 64) -> Document:
    return Document.objects.create(
        dataset=dataset,
        original_filename="statement.pdf",
        mime_type="application/pdf",
        file_format="pdf",
        sha256=digest,
        size_bytes=128,
        storage_path=f"documents/{digest}.pdf",
    )


def test_health_check_configuration_uses_the_v4_api_only():
    assert settings.INSTALLED_APPS.count("health_check") == 1
    assert not any(app.startswith("health_check.") for app in settings.INSTALLED_APPS)
    assert not any(name.startswith("HEALTH_CHECK_") for name in dir(settings))
    assert CORE_HEALTH_CHECKS == (
        "health_check.Cache",
        "health_check.Database",
        "health_check.Storage",
    )
    assert SystemHealthView.checks is CORE_HEALTH_CHECKS


def test_health_probe_checks_configured_dependencies(client):
    response = client.get("/health/?format=json", HTTP_HOST="localhost")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert set(payload["checks"]) == {"cache", "database", "storage"}
    assert {check["status"] for check in payload["checks"].values()} == {"ok"}
    assert all(check["latency_ms"] >= 0 for check in payload["checks"].values())


def test_health_endpoints_separate_liveness_readiness_and_human_status(client):
    liveness = client.get("/health/live/", HTTP_HOST="localhost")
    readiness = client.get("/health/ready/", HTTP_HOST="localhost")
    human_status = client.get("/health/", HTTP_HOST="localhost")

    assert liveness.status_code == 200
    assert liveness.json() == {"status": "ok"}
    assert readiness.status_code == 200
    assert readiness["Content-Type"].startswith("application/json")
    assert readiness.json()["status"] == "ok"
    content = human_status.content.decode()
    assert "All checked services operational" in content
    assert "Document storage" in content
    assert "Synchronous" in content
    assert (
        '<link rel="icon" type="image/svg+xml" href="/static/docai/img/mark-rings.svg">' in content
    )
    assert "alias=" not in content


def test_health_failures_are_sanitized_and_use_service_unavailable(client, monkeypatch):
    from health_check.checks import Database
    from health_check.exceptions import ServiceUnavailable

    def fail_with_sensitive_detail(self):
        del self
        raise ServiceUnavailable("private-db-host.example:1521 rejected secret-value")

    monkeypatch.setattr(Database, "run", fail_with_sensitive_detail)

    response = client.get("/health/ready/", HTTP_HOST="localhost")
    payload = response.json()

    assert response.status_code == 503
    assert payload["status"] == "unavailable"
    assert payload["checks"]["database"]["status"] == "unavailable"
    assert "private-db-host" not in response.content.decode()
    assert "secret-value" not in response.content.decode()

    liveness = client.get("/health/live/", HTTP_HOST="localhost")
    assert liveness.status_code == 200

    for format_name in (None, "text", "atom", "rss", "openmetrics"):
        query = "" if format_name is None else f"?format={format_name}"
        public_response = client.get(f"/health/{query}", HTTP_HOST="localhost")
        content = public_response.content.decode()
        assert "private-db-host" not in content
        assert "secret-value" not in content


def test_category_revisions_are_explicit_and_immutable(api, project):
    created = api.post(
        "/api/v1/categories/",
        {
            "project": str(project.id),
            "key": "bank-statement",
            "name": "Bank statement",
            "description": "Monthly account activity",
        },
        format="json",
    )
    assert created.status_code == 201
    original = created.json()["data"]

    rejected_update = api.patch(
        f"/api/v1/categories/{original['id']}/",
        {"name": "Deposit account statement"},
        format="json",
    )
    updated = api.post(
        f"/api/v1/categories/{original['id']}/revisions/",
        {"name": "Deposit account statement"},
        format="json",
    )

    assert rejected_update.status_code == 405
    assert updated.status_code == 201
    assert updated["Location"].endswith(f"/api/v1/categories/{updated.json()['data']['id']}/")
    revision = updated.json()["data"]
    assert revision["id"] != original["id"]
    assert revision["version"] == 2
    assert revision["name"] == "Deposit account statement"
    assert CategoryDefinition.objects.get(pk=original["id"]).name == "Bank statement"

    duplicate = api.post(
        "/api/v1/categories/",
        {
            "project": str(project.id),
            "key": "bank-statement",
            "name": "Another statement",
            "description": "Duplicate stable key",
        },
        format="json",
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "CONFLICT"


def test_action_payloads_enforce_the_documented_request_schema(
    api, project, dataset, admin, sample_workflow
):
    document = _document(dataset, digest="f" * 64)
    run = run_service.create_run(project, sample_workflow, dataset, admin)
    segment = Segment.objects.create(
        run=run,
        document=document,
        index=0,
        start_unit=0,
        end_unit=1,
        category="w2",
    )
    classification = ClassificationResult.objects.create(
        run=run,
        document=document,
        segment=segment,
        category="w2",
        method="llm",
    )
    requests = [
        (f"/api/v1/segments/{segment.id}/split/", {"at_unit": "second"}, "at_unit"),
        (f"/api/v1/segments/{segment.id}/merge/", {"with": "not-a-uuid"}, "with"),
        (
            f"/api/v1/classifications/{classification.id}/reclassify/",
            {"category": ["w2"]},
            "category",
        ),
    ]

    for path, payload, field in requests:
        response = api.post(path, payload, format="json")
        assert response.status_code == 422
        assert response.json()["error_code"] == "VALIDATION_ERROR"
        assert field in _details(response)


def test_classification_review_queue_is_scoped_to_the_active_dataset(
    api, project, dataset, admin, sample_workflow
):
    other_dataset = Dataset.available_objects.create(
        project=project, name="other", split="dev", created_by=admin
    )
    expected_document = _document(dataset, digest="1" * 64)
    other_document = _document(other_dataset, digest="2" * 64)
    expected_run = run_service.create_run(project, sample_workflow, dataset, admin)
    other_run = run_service.create_run(project, sample_workflow, other_dataset, admin)
    expected = ClassificationResult.objects.create(
        run=expected_run,
        document=expected_document,
        category="other",
        method="llm",
        review_status="needs_review",
    )
    ClassificationResult.objects.create(
        run=other_run,
        document=other_document,
        category="other",
        method="llm",
        review_status="needs_review",
    )

    response = api.get(
        "/api/v1/classifications/",
        {
            "project": str(project.id),
            "dataset": str(dataset.id),
            "review_status": "needs_review",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["count"] == 1
    assert response.json()["data"]["results"][0]["id"] == str(expected.id)


def test_run_history_can_be_scoped_to_a_document(api, project, dataset, admin, sample_workflow):
    document = _document(dataset, digest="3" * 64)
    other_document = _document(dataset, digest="4" * 64)
    Document.objects.filter(pk__in=[document.pk, other_document.pk]).update(status="validated")
    expected = run_service.create_run(
        project,
        sample_workflow,
        dataset,
        admin,
        name="Document result",
        document_ids=[document.id],
    )
    run_service.create_run(
        project,
        sample_workflow,
        dataset,
        admin,
        name="Other document",
        document_ids=[other_document.id],
    )

    response = api.get("/api/v1/runs/", {"document": str(document.id)})

    assert response.status_code == 200
    assert response.json()["data"]["count"] == 1
    result = response.json()["data"]["results"][0]
    assert result["id"] == str(expected.id)
    assert result["workflow_version"] == sample_workflow.version


def test_run_llm_usage_is_aggregated_and_restricted_to_operators(
    project, dataset, admin, operator, viewer, sample_workflow
):
    from rest_framework.test import APIClient

    document = _document(dataset, digest="5" * 64)
    Document.objects.filter(pk=document.pk).update(status="validated")
    run = run_service.create_run(project, sample_workflow, dataset, admin)
    item = run.items.get()
    observe = llm_usage.observer_for(item)
    observe(
        LLMCall(
            system="system",
            user="document",
            schema=ClassificationOut,
            stage="classification",
            prompt_name="classify",
            prompt_version=2,
        ),
        LLMUsage(
            provider="azure_openai",
            model_deployment="extract-v1",
            api_version="2024-10-21",
            input_tokens=100,
            cached_input_tokens=25,
            output_tokens=20,
            reasoning_tokens=5,
            total_tokens=120,
            latency_ms=400,
            finish_reason="stop",
            safety_outcome="clear",
        ),
    )
    observe(
        LLMCall(
            system="system",
            user="document",
            schema=ClassificationOut,
            stage="extraction",
            chunk_index=0,
        ),
        LLMUsage(
            provider="azure_openai",
            model_deployment="extract-v1",
            api_version="2024-10-21",
            input_tokens=200,
            output_tokens=40,
            total_tokens=240,
            latency_ms=600,
            finish_reason="length",
            safety_outcome="flagged",
        ),
    )

    operator_api = APIClient()
    operator_api.force_authenticate(operator)
    response = operator_api.get(f"/api/v1/runs/{run.id}/usage/")

    assert response.status_code == 200
    usage = response.json()["data"]
    assert usage["calls"] == usage["measured_calls"] == 2
    assert usage["input_tokens"] == 300
    assert usage["cached_input_tokens"] == 25
    assert usage["output_tokens"] == 60
    assert usage["reasoning_tokens"] == 5
    assert usage["total_tokens"] == 360
    assert usage["finish_reasons"] == {"length": 1, "stop": 1}
    assert usage["safety_outcomes"] == {"clear": 1, "flagged": 1}
    assert [row["stage"] for row in usage["by_stage"]] == ["classification", "extraction"]
    assert usage["by_item"][0]["run_item"] == str(item.id)
    assert usage["by_item"][0]["document_name"] == document.original_filename
    assert LLMUsageEvent.objects.filter(run=run, run_item=item).count() == 2
    event = LLMUsageEvent.objects.get(run=run, finish_reason="stop")
    assert event.api_version == "2024-10-21" and event.safety_outcome == "clear"
    assert event.run_item.document == document
    assert not hasattr(event, "document_id")

    detail = operator_api.get(f"/api/v1/runs/{run.id}/")
    assert detail.status_code == 200
    assert detail.json()["data"]["used_prompt_versions"] == {
        "classification": {"name": "classify", "version": 2}
    }

    viewer_api = APIClient()
    viewer_api.force_authenticate(viewer)
    forbidden = viewer_api.get(f"/api/v1/runs/{run.id}/usage/")
    assert forbidden.status_code == 403
    assert forbidden.json()["error_code"] == "PERMISSION_DENIED"


def test_prompt_bodies_are_visible_only_to_operators_and_approvers(
    project, admin, operator, approver, reviewer, viewer
):
    from rest_framework.test import APIClient

    prompt = governance.ensure_default_prompts(admin)["extraction"]
    url = f"/api/v1/prompts/?name={prompt.name}&version={prompt.version}"

    for user in (operator, approver):
        client = APIClient()
        client.force_authenticate(user)
        response = client.get(url)
        assert response.status_code == 200
        result = response.json()["data"]["results"][0]
        assert result["id"] == str(prompt.id)
        assert result["system_prompt"] == prompt.system_prompt
        assert result["user_template"] == prompt.user_template

    for user in (reviewer, viewer):
        client = APIClient()
        client.force_authenticate(user)
        response = client.get(url)
        assert response.status_code == 403
        assert response.json()["error_code"] == "PERMISSION_DENIED"


def test_workflow_validation_requires_a_typed_request(api):
    response = api.post("/api/v1/workflows/validate/", {}, format="json")

    assert response.status_code == 422
    assert set(_details(response)) == {"workflow_type", "config"}


def test_evaluation_create_rejects_bad_identifiers_and_tolerance(api):
    invalid_id = api.post("/api/v1/evaluations/", {"run": "not-a-uuid"}, format="json")
    assert invalid_id.status_code == 422
    assert "run" in _details(invalid_id)

    invalid_tolerance = api.post(
        "/api/v1/evaluations/",
        {"run": str(uuid.uuid4()), "numeric_tolerance": -0.1},
        format="json",
    )
    assert invalid_tolerance.status_code == 422
    assert "numeric_tolerance" in _details(invalid_tolerance)


def test_rate_limit_envelope_preserves_retry_after_header():
    response = docai_exception_handler(Throttled(wait=7), {})

    assert response is not None
    assert response.status_code == 429
    assert response["Retry-After"] == "7"
    assert response.data["error_code"] == "RATE_LIMITED"


def test_label_api_supports_absent_and_document_category_modes(api, dataset):
    document = _document(dataset)

    absent = api.post(
        "/api/v1/labels/",
        {"document": str(document.id), "mode": "absent", "field_name": "routing_number"},
        format="json",
    )
    category = api.post(
        "/api/v1/labels/",
        {"document": str(document.id), "mode": "category", "category": "bank-statement"},
        format="json",
    )

    assert absent.status_code == 201
    assert absent["Location"].endswith(f"/api/v1/labels/{absent.json()['data']['id']}/")
    assert absent.json()["data"]["is_absent"] is True
    assert category.status_code == 201
    assert category.json()["data"]["category"] == "bank-statement"


def test_unknown_routes_invalid_versions_and_csrf_failures_use_json_contract(viewer):
    from rest_framework.test import APIClient

    browser = APIClient(enforce_csrf_checks=True)
    csrf_failure = browser.post(
        "/api/v1/auth/login/", {"username": "viewer", "password": "pw"}, format="json"
    )
    unknown = browser.get("/api/v1/not-a-resource/")
    invalid_version = browser.get("/api/v2/projects/")

    assert csrf_failure.status_code == 403
    assert csrf_failure["Content-Type"].startswith("application/json")
    assert csrf_failure.json()["error_code"] == "CSRF_FAILED"
    assert _details(csrf_failure)["csrf"]["code"] == "csrf_failed"
    for response in (unknown, invalid_version):
        assert response.status_code == 404
        assert response["Content-Type"].startswith("application/json")
        assert response.json()["error_code"] == "NOT_FOUND"


def test_field_promotion_is_a_separate_approver_operation(
    api, reviewer, project, dataset, admin, sample_workflow
):
    from rest_framework.test import APIClient

    document = _document(dataset, digest="e" * 64)
    run = run_service.create_run(project, sample_workflow, dataset, admin)
    field = ExtractedField.objects.create(
        run=run,
        document=document,
        name="account_number",
        raw_value="1234",
        reviewed_value="1234",
        review_status="accepted",
    )
    reviewer_api = APIClient()
    reviewer_api.force_authenticate(reviewer)

    denied = reviewer_api.post(f"/api/v1/fields/{field.id}/promote/", {}, format="json")
    legacy = reviewer_api.post(
        f"/api/v1/fields/{field.id}/review/", {"action": "promote"}, format="json"
    )
    promoted = api.post(
        f"/api/v1/fields/{field.id}/promote/", {"reason": "verified"}, format="json"
    )

    assert denied.status_code == 403
    assert legacy.status_code == 422
    assert _details(legacy)["action"]["code"] == "invalid_choice"
    assert promoted.status_code == 201
    label_id = promoted.json()["data"]["id"]
    assert promoted["Location"].endswith(f"/api/v1/labels/{label_id}/")
    assert GroundTruthLabel.objects.get(pk=label_id).notes == "verified"


def test_evaluation_uses_latest_final_label_deterministically(
    project, dataset, admin, sample_workflow
):
    document = _document(dataset, digest="d" * 64)
    document.status = "validated"
    document.save(update_fields=["status", "status_changed", "modified"])
    run = run_service.create_run(project, sample_workflow, dataset, admin)
    ExtractedField.objects.create(
        run=run,
        document=document,
        name="employee_ssn",
        raw_value="222-22-2222",
    )
    GroundTruthLabel.objects.create(
        document=document,
        kind="field",
        field_name="employee_ssn",
        expected_value="111-11-1111",
        version=1,
        status="final",
    )
    GroundTruthLabel.objects.create(
        document=document,
        kind="field",
        field_name="employee_ssn",
        expected_value="222-22-2222",
        version=2,
        status="final",
    )

    metrics = evaluation_service.metrics_for_run(run)

    assert metrics["extraction"]["aggregate"]["precision"] == 1.0


def test_run_create_always_returns_an_async_handle(
    api, project, dataset, sample_workflow, monkeypatch
):
    scheduled = []

    def schedule(run_id):
        run = run_service.Run.objects.get(pk=run_id)
        run.status = "running"
        scheduled.append(run_id)
        return run

    monkeypatch.setattr(execution_service, "schedule_run", schedule)
    response = api.post(
        "/api/v1/runs/",
        {
            "project": str(project.id),
            "workflow": str(sample_workflow.id),
            "dataset": str(dataset.id),
        },
        format="json",
    )

    assert response.status_code == 202
    assert scheduled == [run_service.Run.objects.get().pk]
    assert response["Retry-After"] == "2"
    assert response["Location"].endswith(f"/api/v1/runs/{response.json()['data']['id']}/")


def test_cancel_queued_run_returns_completed_state(api, project, dataset, admin, sample_workflow):
    run = run_service.create_run(project, sample_workflow, dataset, admin)

    response = api.post(f"/api/v1/runs/{run.id}/cancel/", {}, format="json")

    assert response.status_code == 200
    assert response["Location"].endswith(f"/api/v1/runs/{run.id}/")
    assert response.json()["data"]["status"] == "cancelled"
    assert response.json()["data"]["cancel_requested"] is True
