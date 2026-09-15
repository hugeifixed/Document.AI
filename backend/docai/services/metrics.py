"""Bounded workspace aggregates over recorded executions, decisions and responses.

Duration windows return at most three boundary rows per partition. Classification
counts correlate run AND document and count distinct executions, never filenames.
No joins to JSON values or vendor-specific percentile functions are needed.
"""

import json
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db.models import (
    Case,
    CharField,
    Count,
    Exists,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
    Window,
)
from django.db.models.functions import Ceil, Coalesce, Floor, NullIf, RowNumber, TruncDate
from django.utils import timezone

from docai.models import (
    ClassificationResult,
    Document,
    ExtractedField,
    LLMUsageEvent,
    ReviewAction,
    Run,
    RunItem,
)

UNCLASSIFIED = "__unclassified__"
PHASES = {
    "preparation": ("Preparation", ["normalization"]),
    "layout": ("Layout", ["layout"]),
    "workflow": ("Workflow", ["workflow"]),
    "persistence": ("Persistence", ["persist"]),
    "worker_dispatch": (
        "Worker / dispatch",
        [
            "delivery_limit",
            "execution_interrupted",
            "retry_dispatch_failed",
            "local_queue_lost",
            "worker_lost",
            "dispatch_failed",
        ],
    ),
    "unknown": ("Unknown", []),
}


def period(queryset, field, filters):
    start = datetime.combine(filters["start"], time.min, tzinfo=UTC)
    end = datetime.combine(filters["end"] + timedelta(days=1), time.min, tzinfo=UTC)
    return queryset.filter(**{f"{field}__gte": start, f"{field}__lt": end})


def dates(filters):
    return [
        filters["start"] + timedelta(days=i)
        for i in range((filters["end"] - filters["start"]).days + 1)
    ]


def percentage(numerator, denominator):
    return 100 * numerator / denominator if denominator else None


def duration_boundaries(items, *, daily=False):
    samples = items.filter(duration_ms__isnull=False).order_by()
    partition = [TruncDate("status_changed", tzinfo=UTC)] if daily else None
    ranked = (
        samples.annotate(
            sample_rank=Window(
                RowNumber(),
                partition_by=partition,
                order_by=[F("duration_ms").asc(), F("pk").asc()],
            ),
            sample_count=Window(Count("pk"), partition_by=partition),
        )
        .annotate(
            median_low=Floor((F("sample_count") + 1) / 2.0),
            median_high=Floor((F("sample_count") + 2) / 2.0),
            p95_rank=Ceil(F("sample_count") * 0.95),
        )
        .filter(
            Q(sample_rank=F("median_low"))
            | Q(sample_rank=F("median_high"))
            | Q(sample_rank=F("p95_rank"))
        )
    )
    if daily:
        ranked = ranked.annotate(day=TruncDate("status_changed", tzinfo=UTC))
    fields = ["duration_ms", "sample_rank", "sample_count", "median_low", "median_high", "p95_rank"]
    result: dict[Any, dict[str, Any]] = {}
    for row in ranked.values(*fields, *(["day"] if daily else [])):
        key = row["day"] if daily else None
        value = result.setdefault(
            key,
            {"duration_sample_count": row["sample_count"], "middle": [], "p95_duration_ms": None},
        )
        if row["sample_rank"] in (row["median_low"], row["median_high"]):
            value["middle"].append(row["duration_ms"])
        if row["sample_rank"] == row["p95_rank"]:
            value["p95_duration_ms"] = row["duration_ms"]
    for value in result.values():
        middle = value.pop("middle")
        value["median_duration_ms"] = sum(middle) / len(middle)
    return result


def empty_duration():
    return {"duration_sample_count": 0, "median_duration_ms": None, "p95_duration_ms": None}


def effective_types():
    # NullIf handles Oracle's empty-string-as-NULL semantics too.
    return ClassificationResult.objects.annotate(
        effective_category=Coalesce(
            NullIf("reviewed_category", Value("")),
            "category",
            Value(UNCLASSIFIED),
            output_field=CharField(),
        )
    )


def type_counts(items):
    execution = items.filter(
        run_id=OuterRef("run_id"), document_id=OuterRef("document_id")
    ).order_by()
    rows = (
        effective_types()
        .annotate(execution_id=Subquery(execution.values("pk")[:1]))
        .filter(execution_id__isnull=False)
        .order_by()
        .values("effective_category")
        .annotate(executions=Count("execution_id", distinct=True))
    )
    counts = {row["effective_category"]: row["executions"] for row in rows}
    missing = items.filter(
        ~Exists(
            ClassificationResult.objects.filter(
                run_id=OuterRef("run_id"), document_id=OuterRef("document_id")
            )
        )
    ).count()
    if missing:
        counts[UNCLASSIFIED] = counts.get(UNCLASSIFIED, 0) + missing
    return sorted(
        [
            {
                "key": key,
                "label": "Not classified" if key == UNCLASSIFIED else key,
                "executions": count,
            }
            for key, count in counts.items()
        ],
        key=lambda row: (-row["executions"], row["key"]),
    )


def processing(runs, filters):
    base = period(
        RunItem.objects.filter(run__in=runs, status__in=["succeeded", "failed"]),
        "status_changed",
        filters,
    )
    options = [{"key": row["key"], "label": row["label"]} for row in type_counts(base)]
    items = base
    if filters.get("status"):
        items = items.filter(status=filters["status"])
    if filters.get("document_type"):
        matching = effective_types().filter(
            run_id=OuterRef("run_id"), document_id=OuterRef("document_id")
        )
        if filters["document_type"] == UNCLASSIFIED:
            items = items.filter(
                ~Exists(matching) | Exists(matching.filter(effective_category=UNCLASSIFIED))
            )
        else:
            items = items.filter(
                Exists(matching.filter(effective_category=filters["document_type"]))
            )
    daily_counts = {
        row["day"]: row
        for row in items.order_by()
        .annotate(day=TruncDate("status_changed", tzinfo=UTC))
        .values("day")
        .annotate(
            completed_jobs=Count("pk"),
            succeeded=Count("pk", filter=Q(status="succeeded")),
            failed=Count("pk", filter=Q(status="failed")),
        )
    }
    durations = duration_boundaries(items, daily=True)
    daily = [
        {
            "date": day,
            **{"completed_jobs": 0, "succeeded": 0, "failed": 0},
            **{k: v for k, v in daily_counts.get(day, {}).items() if k != "day"},
            **durations.get(day, empty_duration()),
        }
        for day in dates(filters)
    ]
    phase = Case(
        *[When(stage__in=stages, then=Value(key)) for key, (_, stages) in PHASES.items() if stages],
        default=Value("unknown"),
        output_field=CharField(),
    )
    failures = {
        row["phase"]: row["count"]
        for row in items.filter(status="failed")
        .order_by()
        .annotate(phase=phase)
        .values("phase")
        .annotate(count=Count("pk"))
    }
    return {
        "completed_jobs": sum(row["completed_jobs"] for row in daily),
        **duration_boundaries(items).get(None, empty_duration()),
        "daily": daily,
        "by_document_type": type_counts(items),
        "document_type_options": options,
        "failures_by_phase": sorted(
            [
                {"key": key, "label": label, "count": failures.get(key, 0)}
                for key, (label, _) in PHASES.items()
            ],
            key=lambda row: (-row["count"], row["key"]),
        ),
    }


def run_metrics(runs, filters):
    statuses = ["succeeded", "failed", "partial", "cancelled"]
    rows = (
        period(runs.filter(status__in=statuses), "finished_at", filters)
        .order_by()
        .annotate(day=TruncDate("finished_at", tzinfo=UTC))
        .values("day", "status")
        .annotate(count=Count("pk"))
    )
    days = {day: {"date": day, **dict.fromkeys(statuses, 0)} for day in dates(filters)}
    totals = dict.fromkeys(statuses, 0)
    for row in rows:
        days[row["day"]][row["status"]] = row["count"]
        totals[row["status"]] += row["count"]
    return {
        **totals,
        "success_rate": percentage(
            totals["succeeded"], totals["succeeded"] + totals["failed"] + totals["partial"]
        ),
        "daily": list(days.values()),
    }


def review_metrics(runs, filters):
    fields = ExtractedField.objects.filter(run__in=runs, review_status="needs_review")
    classifications = ClassificationResult.objects.filter(
        run__in=runs, review_status="needs_review"
    )
    field_actions = Q(
        field__run__in=runs, action__in=["accept", "correct", "reject", "mark_absent"]
    )
    classification_actions = Q(classification__run__in=runs, action__in=["accept", "reclassify"])
    decisions = period(
        ReviewAction.objects.filter(field_actions | classification_actions), "created", filters
    )
    totals = decisions.aggregate(
        decision_count=Count("pk"),
        field_decision_count=Count("pk", filter=field_actions),
        field_correction_count=Count("pk", filter=field_actions & Q(action="correct")),
    )
    daily = {
        row["day"]: row
        for row in decisions.order_by()
        .annotate(day=TruncDate("created", tzinfo=UTC))
        .values("day")
        .annotate(
            field_decisions=Count("pk", filter=field_actions),
            classification_decisions=Count("pk", filter=classification_actions),
        )
    }
    return {
        **totals,
        "backlog_fields": fields.count(),
        "backlog_classifications": classifications.count(),
        "backlog_documents": Document.objects.filter(
            Q(pk__in=fields.values("document_id")) | Q(pk__in=classifications.values("document_id"))
        ).count(),
        "field_correction_rate": percentage(
            totals["field_correction_count"], totals["field_decision_count"]
        ),
        "daily": [
            {
                "date": day,
                "field_decisions": daily.get(day, {}).get("field_decisions", 0),
                "classification_decisions": daily.get(day, {}).get("classification_decisions", 0),
            }
            for day in dates(filters)
        ],
    }


def usage_metrics(runs, filters):
    events = period(LLMUsageEvent.objects.filter(run__in=runs), "created", filters)
    options = {
        key: list(
            events.exclude(**{field: ""}).order_by(field).values_list(field, flat=True).distinct()
        )
        for key, field in [
            ("providers", "provider"),
            ("deployments", "model_deployment"),
            ("stages", "stage"),
        ]
    }
    for key, field in [
        ("provider", "provider"),
        ("deployment", "model_deployment"),
        ("stage", "stage"),
    ]:
        if filters.get(key):
            events = events.filter(**{field: filters[key]})
    aggregates = {
        "calls": Count("pk"),
        "measured_calls": Count("total_tokens"),
        "total_tokens": Sum("total_tokens"),
    }
    totals = events.aggregate(**aggregates)
    if not totals["calls"]:
        totals["total_tokens"] = 0
    daily = {
        row["day"]: row
        for row in events.order_by()
        .annotate(day=TruncDate("created", tzinfo=UTC))
        .values("day")
        .annotate(**aggregates)
    }
    return {
        **totals,
        "daily": [
            {"date": day, **{key: daily.get(day, {}).get(key, 0) for key in aggregates}}
            for day in dates(filters)
        ],
        "filter_options": options,
    }


def snapshot(*, filters, project_ids, user, roles, usage=False):
    canonical = {key: str(value) for key, value in filters.items()}
    identity = [
        canonical,
        sorted(str(pk) for pk in project_ids),
        str(user.pk),
        sorted(roles),
        usage,
    ]
    key = "docai:metrics:v1:" + sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached
    runs = Run.objects.filter(project_id__in=project_ids, dataset__is_removed=False)
    if filters.get("dataset"):
        runs = runs.filter(dataset_id=filters["dataset"])
    ttl = settings.DOCAI_CACHE_TTLS["metrics"]
    data = {
        "meta": {
            "start_date": filters["start"],
            "end_date": filters["end"],
            "timezone": "UTC",
            "as_of": timezone.now(),
            "cache_ttl_seconds": ttl,
            "applied_filters": canonical,
        }
    }
    if usage:
        data.update(usage_metrics(runs, filters))
    else:
        data.update(
            processing=processing(runs, filters),
            runs=run_metrics(runs, filters),
            review=review_metrics(runs, filters),
        )
    cache.set(key, data, ttl)
    return data
