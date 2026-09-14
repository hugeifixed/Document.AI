"""Persist provider-neutral LLM usage and build role-safe run summaries.

This service is the ORM boundary. Adapters report content-free metadata through
an observer and never import Django models or know about runs and documents.
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import BigIntegerField, Count, Sum
from django.db.models.functions import Coalesce

from docai.adapters.llm.base import LLMCall, LLMUsage, LLMUsageObserver
from docai.logging.context import get_trace_id
from docai.models import RUN_STATUS, LLMUsageEvent, Run, RunItem


def observer_for(run_item: RunItem) -> LLMUsageObserver:
    """Bind provider responses to the durable run/document execution context."""

    def record(call: LLMCall, usage: LLMUsage) -> None:
        actor_id = run_item.run.created_by_id
        LLMUsageEvent.objects.create(
            run_id=run_item.run_id,
            run_item_id=run_item.id,
            stage=call.stage or call.prompt_name or "unknown",
            chunk_index=call.chunk_index,
            segment_index=call.segment_index,
            attempt=max(run_item.attempts, 1),
            provider=usage.provider,
            model_deployment=usage.model_deployment,
            model_name=usage.model_name,
            provider_request_id=usage.provider_request_id,
            api_version=usage.api_version,
            prompt_name=call.prompt_name,
            prompt_version=call.prompt_version,
            schema_name=call.schema_name,
            schema_version=call.schema_version,
            input_tokens=usage.input_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            total_tokens=usage.total_tokens,
            latency_ms=usage.latency_ms,
            outcome=usage.outcome,
            finish_reason=usage.finish_reason,
            safety_outcome=usage.safety_outcome,
            correlation_id=get_trace_id() or run_item.correlation_id,
            created_by_id=actor_id,
        )

    return record


def prompt_versions_used(run: Run) -> dict[str, dict[str, str | int]]:
    """Return content-free prompt provenance for provider responses in a run."""
    rows = (
        LLMUsageEvent.objects.filter(run=run)
        .exclude(prompt_name="")
        .exclude(prompt_version__isnull=True)
        .values("stage", "prompt_name", "prompt_version")
        .order_by("stage", "prompt_name", "prompt_version")
        .distinct()
    )
    versions: dict[str, dict[str, str | int]] = {}
    for row in rows:
        version = row["prompt_version"]
        if version is None:  # Defensive narrowing; the query excludes this case.
            continue
        versions[str(row["stage"])] = {
            "name": str(row["prompt_name"]),
            "version": version,
        }
    return versions


def _annotated(queryset):
    zero = 0
    return queryset.annotate(
        calls=Count("id"),
        measured_calls=Count("total_tokens"),
        input_tokens=Coalesce(Sum("input_tokens"), zero, output_field=BigIntegerField()),
        cached_input_tokens=Coalesce(
            Sum("cached_input_tokens"), zero, output_field=BigIntegerField()
        ),
        output_tokens=Coalesce(Sum("output_tokens"), zero, output_field=BigIntegerField()),
        reasoning_tokens=Coalesce(Sum("reasoning_tokens"), zero, output_field=BigIntegerField()),
        total_tokens=Coalesce(Sum("total_tokens"), zero, output_field=BigIntegerField()),
    )


def summarize_run(run: Run) -> dict:
    """Return totals plus stage and document-job rollups; never model content."""
    events = LLMUsageEvent.objects.filter(run=run)
    # Events are append-only. One indexed count detects writes from other workers
    # even with process-local caches. Run revision covers retries and completion.
    # A concurrent append makes the next read miss, even if it races this fill.
    revision = (run.modified.isoformat(), run.status, events.count())
    key = f"docai:llm-usage:v1:{run.pk}"
    cached = cache.get(key)
    if cached is not None and cached["revision"] == revision:
        return dict(cached["summary"])
    finish_reasons = {
        row["finish_reason"]: row["calls"]
        for row in events.exclude(finish_reason="")
        .values("finish_reason")
        .annotate(calls=Count("id"))
        .order_by("finish_reason")
    }
    safety_outcomes = {
        row["safety_outcome"]: row["calls"]
        for row in events.values("safety_outcome")
        .annotate(calls=Count("id"))
        .order_by("safety_outcome")
    }
    totals = events.aggregate(
        calls=Count("id"),
        measured_calls=Count("total_tokens"),
        input_tokens=Coalesce(Sum("input_tokens"), 0, output_field=BigIntegerField()),
        cached_input_tokens=Coalesce(Sum("cached_input_tokens"), 0, output_field=BigIntegerField()),
        output_tokens=Coalesce(Sum("output_tokens"), 0, output_field=BigIntegerField()),
        reasoning_tokens=Coalesce(Sum("reasoning_tokens"), 0, output_field=BigIntegerField()),
        total_tokens=Coalesce(Sum("total_tokens"), 0, output_field=BigIntegerField()),
    )
    by_stage = list(
        _annotated(events.values("stage"))
        .order_by("stage")
        .values(
            "stage",
            "calls",
            "measured_calls",
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
    )
    by_item = list(
        _annotated(
            events.values(
                "run_item_id",
                "run_item__document_id",
                "run_item__document__original_filename",
            )
        )
        .order_by("run_item__document__original_filename", "run_item_id")
        .values(
            "run_item_id",
            "run_item__document_id",
            "run_item__document__original_filename",
            "calls",
            "measured_calls",
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
    )
    summary = {
        "run": str(run.id),
        **totals,
        "finish_reasons": finish_reasons,
        "safety_outcomes": safety_outcomes,
        "by_stage": by_stage,
        "by_item": [
            {
                "run_item": str(row["run_item_id"]),
                "document": str(row["run_item__document_id"]),
                "document_name": row["run_item__document__original_filename"],
                "calls": row["calls"],
                "measured_calls": row["measured_calls"],
                "input_tokens": row["input_tokens"],
                "cached_input_tokens": row["cached_input_tokens"],
                "output_tokens": row["output_tokens"],
                "reasoning_tokens": row["reasoning_tokens"],
                "total_tokens": row["total_tokens"],
            }
            for row in by_item
        ],
    }
    ttl_key = (
        "llm_usage_active"
        if run.status in (RUN_STATUS.queued, RUN_STATUS.running)
        else "llm_usage_complete"
    )
    transaction.on_commit(
        lambda: cache.set(
            key,
            {"revision": revision, "summary": summary},
            settings.DOCAI_CACHE_TTLS[ttl_key],
        )
    )
    return summary
