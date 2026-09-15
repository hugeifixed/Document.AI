import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import quote
from uuid import uuid4

import pytest
from dj_cache_panel.cache_panel import get_cache_panel
from django.core.cache import cache
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from docai.models import (
    ClassificationResult,
    Dataset,
    Document,
    ExtractedField,
    LLMUsageEvent,
    ReviewAction,
    Run,
    RunItem,
)
from docai.services import metrics

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_cache(settings):
    if "silk" in settings.INSTALLED_APPS:
        from silk.collector import DataCollector

        DataCollector().clear()
    cache.clear()
    with patch("django.utils.timezone.now", return_value=NOW):
        yield
    cache.clear()


@pytest.fixture
def run(project, dataset, sample_workflow):
    return Run.objects.create(
        project=project,
        dataset=dataset,
        workflow=sample_workflow,
        config_snapshot={},
        config_hash="test",
        status="succeeded",
        finished_at=NOW,
    )


def item(run, duration=None, status="succeeded", at=NOW, document=None, stage="done"):
    document = document or Document.objects.create(
        dataset=run.dataset,
        original_filename="private.pdf",
        sha256=uuid4().hex * 2,
        file_format="pdf",
        size_bytes=1,
        storage_path="private.pdf",
    )
    result = RunItem.objects.create(
        run=run,
        document=document,
        idempotency_key=uuid4().hex,
        duration_ms=duration,
        status=status,
        stage=stage,
    )
    RunItem.objects.filter(pk=result.pk).update(status_changed=at)
    return result


def payload(api, url="/api/v1/metrics/", **params):
    response = api.get(url, params)
    assert response.status_code == 200, response.content
    assert response["Cache-Control"] == "private, no-store"
    return response.json()["data"]


def test_empty_and_zero(api, run):
    data = payload(api, range="today")
    assert data["processing"]["completed_jobs"] == 0
    assert data["processing"]["median_duration_ms"] is None
    assert data["review"]["field_correction_rate"] is None
    assert len(data["processing"]["daily"]) == 1
    assert data["meta"]["timezone"] == "UTC"
    assert data["meta"]["cache_ttl_seconds"] == 60
    assert payload(api, "/api/v1/metrics/usage/", range="today")["total_tokens"] == 0
    item(run, 0)
    cache.clear()
    data = payload(api, range="today")
    assert data["processing"]["duration_sample_count"] == 1
    assert data["processing"]["median_duration_ms"] == 0
    assert data["processing"]["p95_duration_ms"] == 0


@pytest.mark.parametrize(
    "values,median,p95",
    [([1], 1, 1), ([1, 9], 5, 9), ([4, 4, 4], 4, 4), (list(range(1, 21)), 10.5, 19)],
)
def test_exact_percentiles_and_null_samples(api, run, values, median, p95):
    for value in values:
        item(run, value)
    item(run)
    data = payload(api, range="today")["processing"]
    assert data["completed_jobs"] == len(values) + 1
    assert data["duration_sample_count"] == len(values)
    assert data["median_duration_ms"] == median
    assert data["p95_duration_ms"] == p95
    assert data["daily"][0]["median_duration_ms"] == median


def test_utc_dates_and_overall_percentiles(api, run):
    item(run, 10, at=datetime(2026, 9, 14, tzinfo=UTC))
    item(run, 20, at=datetime(2026, 9, 15, 23, 59, 59, tzinfo=UTC))
    item(run, 30, at=datetime(2026, 9, 15, tzinfo=UTC))
    item(run, 99, at=datetime(2026, 9, 16, tzinfo=UTC))
    item(run, 99, at=datetime(2026, 9, 13, 23, 59, 59, tzinfo=UTC))
    item(run, 99, status="running")
    data = payload(api, range="custom", start="2026-09-14", end="2026-09-15")["processing"]
    assert data["completed_jobs"] == 3
    assert data["median_duration_ms"] == 20
    assert [row["median_duration_ms"] for row in data["daily"]] == [10, 25]
    assert [row["date"] for row in data["daily"]] == ["2026-09-14", "2026-09-15"]


def test_mixed_reviewed_types_reruns_retries_and_scoped_filters(api, run):
    first = item(run, 100)
    first.attempts = 5
    first.save(update_fields=["attempts"])
    for category, reviewed in [("old", "invoice"), ("invoice", ""), ("receipt", "")]:
        ClassificationResult.objects.create(
            run=run, document=first.document, category=category, reviewed_category=reviewed
        )
    other_run = Run.objects.create(
        project=run.project,
        dataset=run.dataset,
        workflow=run.workflow,
        config_snapshot={},
        config_hash="rerun",
        status="failed",
        finished_at=NOW,
    )
    item(other_run, 30, status="failed", document=first.document, stage="normalization")
    data = payload(api, range="today")
    assert data["processing"]["completed_jobs"] == 2
    assert {row["key"]: row["executions"] for row in data["processing"]["by_document_type"]} == {
        "invoice": 1,
        "receipt": 1,
        "__unclassified__": 1,
    }
    filtered = payload(api, range="today", status="succeeded", document_type="invoice")
    assert filtered["processing"]["completed_jobs"] == 1
    assert filtered["runs"] == data["runs"]
    assert filtered["review"] == data["review"]
    assert (
        filtered["processing"]["document_type_options"]
        == data["processing"]["document_type_options"]
    )
    assert payload(api, range="today", document_type="unknown")["processing"]["completed_jobs"] == 0
    assert (
        payload(api, range="today", document_type="__unclassified__")["processing"][
            "completed_jobs"
        ]
        == 1
    )


def test_failure_buckets(api, run):
    for stage in [
        "normalization",
        "layout",
        "workflow",
        "persist",
        "delivery_limit",
        "execution_interrupted",
        "retry_dispatch_failed",
        "worker_lost",
        "local_queue_lost",
        "dispatch_failed",
        "mystery",
    ]:
        item(run, status="failed", stage=stage)
    phases = {
        row["key"]: row["count"]
        for row in payload(api, range="today")["processing"]["failures_by_phase"]
    }
    assert phases == {
        "preparation": 1,
        "layout": 1,
        "workflow": 1,
        "persistence": 1,
        "worker_dispatch": 6,
        "unknown": 1,
    }


def test_runs_reliability_finished_date(api, run):
    for status in ["failed", "partial", "cancelled", "running"]:
        Run.objects.create(
            project=run.project,
            dataset=run.dataset,
            workflow=run.workflow,
            config_snapshot={},
            config_hash=status,
            status=status,
            finished_at=None if status == "running" else NOW,
        )
    data = payload(api, range="today")["runs"]
    assert data["success_rate"] == pytest.approx(100 / 3)
    assert {
        key: data[key] for key in ["succeeded", "failed", "partial", "cancelled"]
    } == dict.fromkeys(["succeeded", "failed", "partial", "cancelled"], 1)
    run.finished_at = NOW - timedelta(days=10)
    run.save(update_fields=["finished_at"])
    cache.clear()
    assert payload(api, range="today")["runs"]["succeeded"] == 0


def test_review_backlog_and_repeated_decisions(api, run):
    job = item(run, at=NOW - timedelta(days=100))
    field = ExtractedField.objects.create(
        run=run, document=job.document, name="test", review_status="needs_review"
    )
    classification = ClassificationResult.objects.create(
        run=run, document=job.document, category="invoice", review_status="needs_review"
    )
    for action in ["accept", "correct", "correct", "reject", "mark_absent"]:
        ReviewAction.objects.create(field=field, action=action)
    for action in ["accept", "reclassify"]:
        ReviewAction.objects.create(classification=classification, action=action)
    ReviewAction.objects.create(field=field, action="promote")
    old = ReviewAction.objects.create(field=field, action="correct")
    ReviewAction.objects.filter(pk=old.pk).update(created=NOW - timedelta(days=100))
    data = payload(api, range="today")["review"]
    assert (
        data["backlog_fields"] == data["backlog_classifications"] == data["backlog_documents"] == 1
    )
    assert data["decision_count"] == 7
    assert data["field_decision_count"] == 5
    assert data["field_correction_count"] == 2
    assert data["field_correction_rate"] == 40
    assert data["daily"][0]["classification_decisions"] == 2


def test_usage_unknown_partial_zero_and_filters(api, run):
    job = item(run)
    for tokens, provider, stage, attempt in [
        (None, "a", "classify", 1),
        (0, "a", "extract", 1),
        (15, "b", "extract", 2),
    ]:
        LLMUsageEvent.objects.create(
            run=run,
            run_item=job,
            provider=provider,
            stage=stage,
            model_deployment="deployment",
            total_tokens=tokens,
            attempt=attempt,
        )
    data = payload(api, "/api/v1/metrics/usage/", range="today")
    assert (data["calls"], data["measured_calls"], data["total_tokens"]) == (3, 2, 15)
    unknown = payload(api, "/api/v1/metrics/usage/", range="today", stage="classify")
    assert unknown["total_tokens"] is None
    assert unknown["daily"][0]["total_tokens"] is None
    assert unknown["filter_options"] == data["filter_options"]
    zero = payload(api, "/api/v1/metrics/usage/", range="today", provider="a", stage="extract")
    assert (zero["calls"], zero["measured_calls"], zero["total_tokens"]) == (1, 1, 0)
    empty = payload(api, "/api/v1/metrics/usage/", range="today", provider="missing")
    assert empty["calls"] == empty["total_tokens"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"range": "bad"},
        {"range": "custom"},
        {"range": "custom", "start": "no", "end": "2026-09-15"},
        {"range": "custom", "start": "2026-09-15", "end": "2026-09-14"},
        {"range": "custom", "start": "2026-06-01", "end": "2026-09-15"},
        {"range": "custom", "start": "2026-09-15", "end": "2026-09-16"},
        {"start": "2026-09-01"},
        {"provider": "a"},
        {"status": "running"},
        {"project": "no"},
        {"document_type": "a" * 65},
    ],
)
def test_invalid_filters(api, params):
    response = api.get("/api/v1/metrics/", params)
    assert response.status_code == 400
    assert response.json()["success"] is False


def test_scope_validation_and_unavailable_scopes(api, run):
    other = Dataset.available_objects.create(project=run.project, name="other")
    assert api.get("/api/v1/metrics/", {"dataset": str(uuid4())}).status_code == 404
    assert api.get("/api/v1/metrics/", {"project": str(uuid4())}).status_code == 404
    from docai.models import Project

    other_project = Project.available_objects.create(name="Other", slug="other")
    assert (
        api.get(
            "/api/v1/metrics/", {"project": str(other_project.pk), "dataset": str(other.pk)}
        ).status_code
        == 400
    )
    item(run, 1)
    assert payload(api, dataset=str(run.dataset_id))["processing"]["completed_jobs"] == 1
    run.dataset.delete()
    assert payload(api)["processing"]["completed_jobs"] == 0
    assert api.get("/api/v1/metrics/", {"dataset": str(run.dataset_id)}).status_code == 404


def test_roles_and_authorization_before_cache(api, run, viewer, operator, reviewer, approver):
    item(run, 1)
    for user in [viewer, reviewer, approver]:
        api.force_authenticate(user)
        assert api.get("/api/v1/metrics/").status_code == 200
        assert api.get("/api/v1/metrics/usage/").status_code == 403
    api.force_authenticate(operator)
    assert api.get("/api/v1/metrics/usage/").status_code == 200
    assert payload(api)["processing"]["completed_jobs"] == 1
    with patch("docai.api.permissions.can_access_project", return_value=False):
        assert payload(api)["processing"]["completed_jobs"] == 0
        assert api.get("/api/v1/metrics/", {"project": str(run.project_id)}).status_code == 403
        assert api.get("/api/v1/metrics/", {"dataset": str(run.dataset_id)}).status_code == 403
    api.force_authenticate(None)
    assert api.get("/api/v1/metrics/").status_code in [401, 403]


def test_cache_caller_role_scope_isolation_and_expiry(api, run, viewer, operator):
    job = item(run, 1)
    first = payload(api, range="today")
    item(run, 2)
    assert payload(api, range="today") == first
    api.force_authenticate(viewer)
    assert payload(api, range="today")["processing"]["completed_jobs"] == 2
    item(run, 3)
    # Same caller, new role set must not reuse its previous snapshot.
    viewer.groups.add(operator.groups.get())
    del viewer._docai_roles
    assert payload(api, range="today")["processing"]["completed_jobs"] == 3
    assert payload(api, range="today", document_type="missing")["processing"]["completed_jobs"] == 0
    with patch("time.time", return_value=__import__("time").time() + 61):
        RunItem.objects.filter(pk=job.pk).update(status="running")
        assert payload(api, range="today")["processing"]["completed_jobs"] == 2


@pytest.mark.parametrize("url", ["/api/v1/metrics/", "/api/v1/metrics/usage/"])
def test_cached_metrics_are_json_safe_and_inspectable(api, admin, run, url):
    item(run, 12)
    cold = payload(api, url, range="today")
    assert payload(api, url, range="today") == cold
    panel = get_cache_panel("default")
    (key,) = panel.query("default", "docai:metrics:*")["keys"]
    client = Client()
    client.force_login(admin)
    # Match the panel's encoded key links, including their escaped colons.
    response = client.get(
        reverse("dj_cache_panel:key_detail", args=["default", quote(key, safe="")])
    )
    assert response.status_code == 200
    cached = panel.get_key(key)["value"]
    assert json.loads(response.context["value_display"]) == json.loads(json.dumps(cached))
    assert cached["meta"]["start_date"] == "2026-09-15"
    assert cached["meta"]["as_of"] == "2026-09-15T12:00:00Z"
    daily = cached["daily"] if url.endswith("usage/") else cached["processing"]["daily"]
    assert daily[0]["date"] == "2026-09-15"


def test_query_count_constant_and_boundary_rows_bounded(run):
    filters = {"start": NOW.date(), "end": NOW.date()}
    item(run, 1)

    def capture():
        with CaptureQueriesContext(connection) as queries:
            result = metrics.processing(Run.objects.filter(pk=run.pk), filters)
        return len(queries), result

    before, _ = capture()
    for value in range(2, 42):
        job = item(run, value)
        ClassificationResult.objects.create(run=run, document=job.document, category="invoice")
    after, result = capture()
    assert before == after
    assert result["median_duration_ms"] == 21
    with CaptureQueriesContext(connection) as queries:
        boundaries = metrics.duration_boundaries(RunItem.objects.all())
    assert len(queries) == 1
    assert "ROW_NUMBER() OVER" in queries[0]["sql"]
    assert boundaries[None]["duration_sample_count"] == 41
    with connection.cursor() as cursor:
        cursor.execute(queries[0]["sql"])
        assert len(cursor.fetchall()) == 2  # Median and P95 boundaries only.


def test_query_edges_and_daily_empty_buckets(api):
    data = payload(api, range="custom", start="2026-06-18", end="2026-09-15")
    assert len(data["processing"]["daily"]) == 90
    assert len(data["runs"]["daily"]) == 90
    assert len(data["review"]["daily"]) == 90
    assert data["runs"]["success_rate"] is None
    assert (
        payload(api, range="", status="", document_type="")["meta"]["applied_filters"]["range"]
        == "30d"
    )
    assert api.get("/api/v1/metrics/?status=failed&status=succeeded").status_code == 400
    assert api.get("/api/v1/metrics/usage/", {"document_type": "a"}).status_code == 400
    assert api.get("/api/v1/metrics/usage/", {"stage": "a" * 33}).status_code == 400
    assert api.get("/api/v1/metrics/usage/", {"deployment": "a" * 121}).status_code == 400


def test_workspace_scope_and_options_respect_period(api, run):
    current = item(run, 10)
    ClassificationResult.objects.create(run=run, document=current.document, category="current")
    old = item(run, 15, at=NOW - timedelta(days=60))
    ClassificationResult.objects.create(run=run, document=old.document, category="old")
    other_dataset = Dataset.available_objects.create(project=run.project, name="another")
    other_run = Run.objects.create(
        project=run.project,
        dataset=other_dataset,
        workflow=run.workflow,
        config_snapshot={},
        config_hash="other",
        status="failed",
        finished_at=NOW,
    )
    other_item = item(other_run, 20)
    ClassificationResult.objects.create(
        run=other_run, document=other_item.document, category="other", review_status="needs_review"
    )
    LLMUsageEvent.objects.create(
        run=other_run, run_item=other_item, provider="other", stage="extract", total_tokens=40
    )
    selected = payload(api, range="today", dataset=str(run.dataset_id))
    assert selected["processing"]["completed_jobs"] == 1
    assert selected["processing"]["document_type_options"] == [
        {"key": "current", "label": "current"}
    ]
    assert selected["runs"]["failed"] == 0
    assert selected["review"]["backlog_classifications"] == 0
    usage = payload(api, "/api/v1/metrics/usage/", range="today", dataset=str(run.dataset_id))
    assert usage["calls"] == 0
    assert usage["filter_options"]["providers"] == []


def test_openapi_metrics_contract():
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(public=True)
    for path in ["/api/v1/metrics/", "/api/v1/metrics/usage/"]:
        operation = schema["paths"][path]["get"]
        assert {"200", "400", "401", "403", "404"} <= operation["responses"].keys()
        properties = operation["responses"]["200"]["content"]["application/json"]["schema"][
            "properties"
        ]
        assert {"success", "data", "message", "trace_id"} <= properties.keys()


def test_aggregates_compile_for_oracle_without_connecting(run):
    pytest.importorskip("oracledb")
    from django.db.backends.oracle.base import DatabaseWrapper
    from django.db.models.sql.compiler import SQLCompiler

    oracle = DatabaseWrapper(
        {"OPTIONS": {}, "NAME": "offline", "TIME_ZONE": "UTC"}, alias="offline"
    )
    oracle.oracle_version = (19,)
    # django-stubs omit this Oracle constant; the public descriptor opens a connection.
    oracle.operators = oracle._standard_operators  # type: ignore[attr-defined]
    statements = []
    original = SQLCompiler.execute_sql

    def compile_and_execute(compiler, *args, **kwargs):
        if compiler.connection.vendor == "sqlite":
            sql, _ = compiler.query.get_compiler(connection=oracle).as_sql()
            statements.append(sql)
        return original(compiler, *args, **kwargs)

    item(run, 10)
    filters = {"start": NOW.date(), "end": NOW.date(), "document_type": "invoice"}
    with patch.object(SQLCompiler, "execute_sql", compile_and_execute):
        runs = Run.objects.filter(pk=run.pk)
        metrics.processing(runs, filters)
        metrics.run_metrics(runs, filters)
        metrics.review_metrics(runs, filters)
        metrics.usage_metrics(runs, filters)
    assert any("ROW_NUMBER() OVER" in sql for sql in statements)
    assert all("PERCENTILE_CONT" not in sql for sql in statements)
