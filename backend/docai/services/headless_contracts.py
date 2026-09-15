"""Bounded, provider-neutral contracts for headless workflow consumers."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urlencode

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Count, QuerySet
from rest_framework.reverse import reverse

from docai.adapters.layout.base import processable_source_formats
from docai.models import CONFIG_STATUS, REVIEW_STATUS, SUPPORTED_MIME, Run, WorkflowConfiguration

_NOTICE_LIMIT = 50
_NOTICE_TEXT_LIMIT = 500
_OUTPUT_CAPABILITIES = {
    "unbundle_classify_extract": ("segments", "classifications", "fields"),
    "classify_structured": ("classifications",),
    "classify_unstructured": ("classifications",),
    "extract_structured": ("fields",),
    "extract_unstructured": ("fields",),
    "extract_template": ("fields",),
}


def _grouped_counts(queryset: QuerySet, field: str) -> dict[str, int]:
    """Use scalar grouping that behaves consistently on SQLite and Oracle."""
    return {
        str(row[field]): row["count"]
        for row in queryset.order_by().values(field).annotate(count=Count("id"))
    }


def _notice(raw: object, default_code: str) -> dict[str, object]:
    if isinstance(raw, dict):
        code = str(raw.get("error_code") or raw.get("code") or default_code)
        message_value = raw.get("message") or raw.get("error_message")
        message = (
            str(message_value)
            if message_value is not None
            else json.dumps(raw, cls=DjangoJSONEncoder, ensure_ascii=False, sort_keys=True)
        )
        retryable = raw.get("retryable")
    else:
        code, message, retryable = default_code, str(raw), None
    return {
        "code": code[:64],
        "message": message[:_NOTICE_TEXT_LIMIT],
        "retryable": retryable if isinstance(retryable, bool) else None,
    }


def _bounded_notices(values: object, default_code: str) -> dict[str, object]:
    raw_values = values if isinstance(values, list) else []
    items = [_notice(value, default_code) for value in raw_values[:_NOTICE_LIMIT]]
    return {
        "count": len(raw_values),
        "truncated": len(raw_values) > len(items),
        "items": items,
    }


def _collection_url(request, name: str, run: Run) -> str:
    return f"{reverse(name, request=request)}?{urlencode({'run': str(run.pk)})}"


def run_result_links(run: Run, request) -> dict[str, object]:
    """Build operation links without querying aggregate result state."""
    results_url = reverse("run-json-results", kwargs={"run_id": run.pk}, request=request)
    exports = {
        fmt: reverse("run-export", kwargs={"pk": run.pk, "fmt": fmt}, request=request)
        for fmt in ("json", "csv", "xlsx")
    }
    workflow_contract_url = None
    if run.workflow.status == CONFIG_STATUS.approved and run.workflow.workflow_type != "evaluate":
        workflow_contract_url = reverse(
            "workflow-contract", kwargs={"workflow_id": run.workflow_id}, request=request
        )
    return {
        "results": results_url,
        "run": reverse("run-detail", kwargs={"pk": run.pk}, request=request),
        "progress": reverse("run-progress", kwargs={"pk": run.pk}, request=request),
        "run_items": _collection_url(request, "run-item-list", run),
        "fields": _collection_url(request, "field-list", run),
        "classifications": _collection_url(request, "classification-list", run),
        "segments": _collection_url(request, "segment-list", run),
        "cancel": reverse("run-cancel", kwargs={"pk": run.pk}, request=request),
        "exports": exports,
        "workflow_contract": workflow_contract_url,
    }


def run_results_manifest(run: Run, request) -> dict[str, object]:
    """Describe a run without materializing its complete result package."""
    item_statuses = _grouped_counts(run.items.all(), "status")
    field_reviews = _grouped_counts(run.fields.all(), "review_status")
    classification_reviews = _grouped_counts(run.classifications.all(), "review_status")
    segment_reviews = _grouped_counts(run.segments.all(), "review_status")
    fields = sum(field_reviews.values())
    classifications = sum(classification_reviews.values())
    segments = sum(segment_reviews.values())
    review = {
        "fields": field_reviews.get(REVIEW_STATUS.needs_review, 0),
        "classifications": classification_reviews.get(REVIEW_STATUS.needs_review, 0),
        "segments": segment_reviews.get(REVIEW_STATUS.needs_review, 0),
    }
    review["total"] = sum(review.values())
    completed = run.status in {"succeeded", "partial", "failed", "cancelled"}
    return {
        "run_id": str(run.pk),
        "client_reference": run.client_reference,
        "status": run.status,
        "completed": completed,
        "stage": run.stage,
        "cancel_requested": run.cancel_requested,
        "created_at": run.created,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "workflow": {
            "id": str(run.workflow_id),
            "name": run.workflow.name,
            "version": run.workflow.version,
            "config_hash": run.config_hash,
        },
        "counts": {
            "run_items": {
                status: item_statuses.get(status, 0)
                for status in ("queued", "running", "succeeded", "failed", "skipped")
            }
            | {"total": sum(item_statuses.values())},
            "fields": fields,
            "classifications": classifications,
            "segments": segments,
        },
        "review": review,
        "warnings": _bounded_notices(run.warnings, "WORKFLOW_WARNING"),
        "errors": _bounded_notices(run.errors, "RUN_ERROR"),
        "links": run_result_links(run, request),
    }


def representation_etag(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        cls=DjangoJSONEncoder,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f'W/"{hashlib.sha256(canonical.encode()).hexdigest()}"'


def _contract_field(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, dict) or not raw.get("name"):
        return None
    enum = raw.get("enum")
    return {
        "name": str(raw["name"]),
        "description": str(raw.get("description") or "")[:500],
        "type": str(raw.get("type") or "string"),
        "required": bool(raw.get("required", False)),
        "enum": [str(value) for value in enum] if isinstance(enum, list) else [],
    }


def _contract_schema(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, dict) or not raw.get("name"):
        return None
    fields = [field for value in raw.get("fields", []) if (field := _contract_field(value))]
    return {
        "name": str(raw["name"]),
        "version": int(raw.get("version") or 1),
        "mode": str(raw.get("mode") or "custom"),
        "fields": fields,
    }


def _output_schemas(workflow: WorkflowConfiguration) -> list[dict[str, object]]:
    config = workflow.config if isinstance(workflow.config, dict) else {}
    candidates: list[object] = []
    configured = config.get("schemas")
    if isinstance(configured, list):
        candidates.extend(configured)
    if config.get("schema"):
        candidates.append(config["schema"])
    if workflow.workflow_type == "extract_template":
        from docai.models import ExtractionTemplate

        template_version = config.get("template_version")
        if not isinstance(template_version, (int, str)):
            return []
        template = (
            ExtractionTemplate.objects.select_related("schema_version")
            .filter(
                project=workflow.project,
                name=config.get("template_name", ""),
                version=template_version,
                status=CONFIG_STATUS.approved,
            )
            .first()
        )
        if template:
            candidates.append(
                {
                    "name": template.schema_version.name,
                    "version": template.schema_version.version,
                    "mode": "custom",
                    "fields": template.schema_version.field_definitions,
                }
            )
    return [schema for value in candidates if (schema := _contract_schema(value))]


def _output_categories(workflow: WorkflowConfiguration) -> list[dict[str, object]]:
    config = workflow.config if isinstance(workflow.config, dict) else {}
    categories: dict[str, dict[str, object]] = {}
    for raw in config.get("categories", []):
        if not isinstance(raw, dict) or not raw.get("key"):
            continue
        key = str(raw["key"])
        categories[key] = {
            "key": key,
            "name": str(raw.get("name") or key),
            "description": str(raw.get("description") or "")[:500],
            "schema": str(raw.get("extraction_schema") or "") or None,
        }
    for raw in config.get("rules", []):
        if not isinstance(raw, dict) or not raw.get("category"):
            continue
        key = str(raw["category"])
        categories.setdefault(
            key,
            {"key": key, "name": key, "description": "", "schema": None},
        )
    return list(categories.values())


def workflow_contract(workflow: WorkflowConfiguration, request) -> dict[str, object]:
    """Expose callable input/output shape while excluding prompts and provider settings."""
    ingestible_formats = sorted(set(SUPPORTED_MIME.values()))
    layout_adapter = str(settings.DOCAI["LAYOUT_ADAPTER"])
    processable_formats = sorted(processable_source_formats(layout_adapter))
    outputs = list(_OUTPUT_CAPABILITIES.get(workflow.workflow_type, ()))
    return {
        "id": str(workflow.pk),
        "project": str(workflow.project_id),
        "name": workflow.name,
        "version": workflow.version,
        "workflow_type": workflow.workflow_type,
        "config_hash": workflow.content_hash,
        "status": workflow.status,
        "input": {
            "ingestible_formats": ingestible_formats,
            "processable_formats": processable_formats,
            "layout_adapter": layout_adapter,
            "invocation_modes": ["document_ids", "multipart_files"],
            "max_batch_files": settings.DOCAI["MAX_BATCH_FILES"],
            "max_file_mb": settings.DOCAI["MAX_UPLOAD_MB"],
            "max_pages": settings.DOCAI["MAX_PAGES"],
            "max_sheets": settings.DOCAI["MAX_SHEETS"],
        },
        "output": {
            "resources": outputs,
            "categories": _output_categories(workflow),
            "schemas": _output_schemas(workflow),
        },
        "links": {
            "workflow": reverse("workflow-detail", kwargs={"pk": workflow.pk}, request=request),
            "invoke": reverse(
                "workflow-invoke", kwargs={"workflow_id": workflow.pk}, request=request
            ),
        },
    }
