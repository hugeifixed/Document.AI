"""Small, application-specific operational panels for Django admin."""

from urllib.parse import urlencode

from dj_control_room_base.core import PanelConfig
from django.conf import settings
from django.db.models import Count, Max, Min, Q
from django.shortcuts import render
from django.urls import reverse

from config.celery_runtime import broker_scheme
from docai.models import ITEM_STATUS, RunItem

processing_errors_config = PanelConfig(
    settings_key="DOCAI_ERROR_PANEL_SETTINGS",
    defaults={"LOAD_DEFAULT_CSS": True, "EXTRA_CSS": []},
)
worker_dashboard_config = PanelConfig(
    settings_key="DOCAI_WORKER_PANEL_SETTINGS",
    defaults={"LOAD_DEFAULT_CSS": True, "EXTRA_CSS": []},
)


def _inspect_celery_workers():
    """Return one bounded live Celery snapshot through the installed panel backend."""
    try:
        from celery import current_app
        from dj_celery_panel.celery_utils import CeleryWorkersInterface

        result = CeleryWorkersInterface(current_app).get_workers()
    except (ImportError, RuntimeError) as exc:
        return [], f"Celery worker inspection is unavailable: {exc}"
    return result.workers_detail, result.error


@worker_dashboard_config.permission_required("workers")
def worker_dashboard(request):
    """Combine configured executor capacity with durable database activity."""
    runner_key = settings.DOCAI["TASK_RUNNER"]
    sqlite_database = "sqlite" in settings.DATABASES["default"]["ENGINE"]
    workers = []
    worker_error = ""
    broker = "None"

    if runner_key == "celery":
        workers, worker_error = _inspect_celery_workers()
        broker = broker_scheme(settings.CELERY_BROKER_URL) or "Not configured"
        runner_label = "Celery"
        configured_capacity = settings.CELERY_WORKER_CONCURRENCY
    elif runner_key == "thread":
        configured_capacity = 1 if sqlite_database else max(1, settings.DOCAI["MAX_WORKERS"])
        runner_label = "Thread pool"
        workers = [
            {
                "name": "In-process executor",
                "status": "on demand",
                "pool": "threads",
                "concurrency": configured_capacity,
                "total_tasks_executed": None,
                "pid": "Web process",
            }
        ]
    else:
        configured_capacity = 1
        runner_label = "Synchronous"
        workers = [
            {
                "name": "Inline executor",
                "status": "on demand",
                "pool": "sync",
                "concurrency": 1,
                "total_tasks_executed": None,
                "pid": "Web process",
            }
        ]

    active_items = RunItem.objects.filter(status__in=(ITEM_STATUS.queued, ITEM_STATUS.running))
    activity_counts = active_items.aggregate(
        queued=Count("id", filter=Q(status=ITEM_STATUS.queued)),
        running=Count("id", filter=Q(status=ITEM_STATUS.running)),
        retry_wait=Count("id", filter=Q(status=ITEM_STATUS.queued, stage="retry_wait")),
    )
    recent_tasks = list(
        RunItem.objects.select_related("document", "run").order_by("-modified")[:25]
    )
    for item in recent_tasks:
        item.admin_url = reverse("admin:docai_runitem_change", args=[item.pk])

    context = worker_dashboard_config.get_context(
        request,
        title="Worker dashboard",
        runner_key=runner_key,
        runner_label=runner_label,
        broker=broker,
        workers=workers,
        worker_error=worker_error,
        live_worker_count=len(workers) if runner_key == "celery" else None,
        configured_capacity=configured_capacity,
        sqlite_limited=runner_key == "thread" and sqlite_database,
        activity_counts=activity_counts,
        recent_tasks=recent_tasks,
    )
    return render(request, "admin/docai/worker_dashboard.html", context)


@processing_errors_config.permission_required("errors")
def processing_errors(request):
    """Summarize current document-processing failures from durable run state."""
    search_query = request.GET.get("q", "").strip()[:100]
    failures = RunItem.objects.filter(status=ITEM_STATUS.failed)
    if search_query:
        failures = failures.filter(
            Q(error_code__icontains=search_query)
            | Q(error_message__icontains=search_query)
            | Q(document__original_filename__icontains=search_query)
            | Q(run__name__icontains=search_query)
        )

    error_groups = list(
        failures.values("error_code")
        .annotate(
            events=Count("id"),
            retryable_events=Count("id", filter=Q(retryable=True)),
            first_seen=Min("modified"),
            last_seen=Max("modified"),
        )
        .order_by("-last_seen")[:100]
    )
    run_item_list = reverse("admin:docai_runitem_changelist")
    for group in error_groups:
        group["admin_url"] = f"{run_item_list}?{
            urlencode(
                {
                    'status__exact': ITEM_STATUS.failed,
                    'error_code__exact': group['error_code'],
                }
            )
        }"

    recent_failures = list(failures.select_related("document", "run").order_by("-modified")[:25])
    for item in recent_failures:
        item.admin_url = reverse("admin:docai_runitem_change", args=[item.pk])

    context = processing_errors_config.get_context(
        request,
        title="Processing errors",
        search_query=search_query,
        error_groups=error_groups,
        group_count=failures.values("error_code").distinct().count(),
        failure_count=failures.count(),
        retryable_count=failures.filter(retryable=True).count(),
        recent_failures=recent_failures,
        run_item_list=run_item_list,
    )
    return render(request, "admin/docai/processing_errors.html", context)
