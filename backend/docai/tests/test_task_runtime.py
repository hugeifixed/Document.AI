from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import Retry
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from config.celery_runtime import (
    current_task_runtime_policy,
    default_filesystem_root,
    default_worker_pool,
    ensure_filesystem_runtime,
    filesystem_path_error,
    filesystem_transport_options,
    projected_filesystem_path_length,
    worker_pool_error,
)
from docai.checks import task_runtime_checks
from docai.exceptions import IntegrationError
from docai.models import ITEM_STATUS, RUN_STATUS
from docai.services import ingestion
from docai.services import run_execution as execution
from docai.services import runs as run_svc
from docai.tasks.celery_tasks import process_run_item


def test_platform_defaults_and_pool_validation():
    assert default_worker_pool("Windows") == "threads"
    assert default_worker_pool("Darwin") == "solo"
    assert default_worker_pool("Linux") == "prefork"
    assert worker_pool_error("threads", "Windows") is None
    assert worker_pool_error("solo", "Windows") is None
    assert worker_pool_error("threads", "Darwin") is None
    assert worker_pool_error("solo", "Darwin") is None
    assert worker_pool_error("prefork", "Linux") is None
    prefork_error = worker_pool_error("prefork", "Windows")
    assert prefork_error is not None and "not supported on Windows" in prefork_error
    macos_error = worker_pool_error("prefork", "Darwin")
    assert macos_error is not None and "macOS" in macos_error and "solo" in macos_error


def test_windows_filesystem_default_uses_short_local_app_data_path():
    root = default_filesystem_root(
        Path("C:/very/deep/source/checkout/data"),
        "Windows",
        {"LOCALAPPDATA": "C:/Users/Omar/AppData/Local"},
    )
    assert root.as_posix() == "C:/Users/Omar/AppData/Local/DocAI/celery"


def test_windows_filesystem_path_budget_rejects_legacy_max_path_overflow():
    short_root = Path("C:/docai-celery")
    long_root = Path("C:/") / ("nested" * 30)

    assert filesystem_path_error(short_root, "Windows") is None
    assert projected_filesystem_path_length(long_root) >= 260
    path_error = filesystem_path_error(long_root, "Windows")
    assert path_error is not None and "C:\\docai-celery" in path_error


def test_filesystem_broker_creates_shared_runtime():
    with TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory) / "celery"
        options = filesystem_transport_options(root)
        paths = ensure_filesystem_runtime(root)

        assert options["data_folder_in"] == options["data_folder_out"]
        assert options["data_folder_in"] == str(paths["messages"])
        assert all(path.is_dir() for path in paths.values())
        assert set(paths) == {"messages", "control"}


@pytest.mark.parametrize("host", ["Windows", "Darwin"])
def test_runtime_check_rejects_unsafe_prefork(host):
    celery_settings = {**settings.DOCAI, "TASK_RUNNER": "celery"}
    with (
        override_settings(
            DOCAI=celery_settings,
            CELERY_BROKER_URL="filesystem://",
            CELERY_RESULT_BACKEND="file:///tmp/results",
            CELERY_WORKER_POOL="prefork",
            DEBUG=True,
        ),
        patch("config.celery_runtime.platform.system", return_value=host),
        patch("docai.checks.importlib.util.find_spec", return_value=object()),
    ):
        issue_ids = {issue.id for issue in task_runtime_checks(None)}

    assert "docai.E005" in issue_ids
    assert ("docai.W001" in issue_ids) is (host == "Windows")


def test_runtime_check_rejects_overlong_windows_filesystem_path():
    celery_settings = {**settings.DOCAI, "TASK_RUNNER": "celery"}
    with (
        override_settings(
            DOCAI=celery_settings,
            CELERY_BROKER_URL="filesystem://",
            CELERY_RESULT_BACKEND="file:///C:/results",
            CELERY_FILESYSTEM_DIR=Path("C:/") / ("nested" * 30),
            CELERY_WORKER_POOL="threads",
            DEBUG=True,
        ),
        patch("config.celery_runtime.platform.system", return_value="Windows"),
        patch("docai.checks.importlib.util.find_spec", return_value=object()),
    ):
        issue_ids = {issue.id for issue in task_runtime_checks(None)}

    assert "docai.E008" in issue_ids


def test_runtime_check_requires_windows_filesystem_locking_dependency():
    celery_settings = {**settings.DOCAI, "TASK_RUNNER": "celery"}

    def installed_module(name):
        return None if name == "pywintypes" else object()

    with (
        override_settings(
            DOCAI=celery_settings,
            CELERY_BROKER_URL="filesystem://",
            CELERY_RESULT_BACKEND=None,
            CELERY_FILESYSTEM_DIR=Path("C:/docai-celery"),
            CELERY_WORKER_POOL="threads",
            DEBUG=True,
        ),
        patch("config.celery_runtime.platform.system", return_value="Windows"),
        patch("docai.checks.importlib.util.find_spec", side_effect=installed_module),
    ):
        issue_ids = {issue.id for issue in task_runtime_checks(None)}

    assert "docai.E007" in issue_ids


def test_runner_selection_has_clear_configuration_error():
    with override_settings(DOCAI={**settings.DOCAI, "TASK_RUNNER": "unknown"}):
        try:
            execution._get_dispatcher()
        except ImproperlyConfigured as exc:
            assert "sync, thread, or celery" in str(exc)
        else:  # pragma: no cover - makes a missing exception an explicit failure
            raise AssertionError("Expected ImproperlyConfigured")


def test_runner_execution_modes_are_explicit():
    assert execution._ThreadDispatcher.is_async is False
    assert execution._CeleryDispatcher.is_async is True


def test_thread_runner_executes_inline_with_sqlite(monkeypatch):
    calls: list[str] = []
    monkeypatch.setitem(settings.DATABASES["default"], "ENGINE", "django.db.backends.sqlite3")

    with (
        patch("docai.services.run_execution.process_item", side_effect=calls.append),
        patch("docai.services.run_execution.ThreadPoolExecutor") as executor,
    ):
        scheduled = execution._ThreadDispatcher().dispatch(
            ["one", "two"], run_id="run", task_ids={}
        )

    assert scheduled is False
    assert calls == ["one", "two"]
    executor.assert_not_called()


def test_thread_runner_keeps_thread_pool_for_server_databases(monkeypatch):
    caller = get_ident()
    worker_threads: list[int] = []
    monkeypatch.setitem(settings.DATABASES["default"], "ENGINE", "django.db.backends.oracle")

    with patch(
        "docai.services.run_execution.process_item",
        side_effect=lambda _: worker_threads.append(get_ident()),
    ):
        scheduled = execution._ThreadDispatcher().dispatch(["one"], run_id="run", task_ids={})

    assert scheduled is False
    assert worker_threads and worker_threads[0] != caller


@pytest.mark.django_db
@pytest.mark.parametrize("runner", ["sync", "thread"])
def test_http_local_schedule_uses_one_process_coordinator(
    project, dataset, admin, sample_workflow, w2_pdf, runner
):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.create_run(project, sample_workflow, dataset, admin)

    with (
        override_settings(DOCAI={**settings.DOCAI, "TASK_RUNNER": runner}),
        patch.object(execution._local_run_coordinator, "submit") as submit,
    ):
        accepted = execution.schedule_run(run.pk)

    accepted.refresh_from_db()
    item = accepted.items.get()
    assert accepted.status == RUN_STATUS.running
    assert accepted.stage == "local_queued"
    assert item.status == ITEM_STATUS.queued
    assert item.stage == "local_queued"
    submit.assert_called_once_with(run.pk, only_failed=False, runner=runner)


def test_local_coordinator_is_singleton_and_serializes_runs():
    coordinator = execution._LocalRunCoordinator()
    executor = SimpleNamespace(submit=MagicMock())

    with patch("docai.services.run_execution.ThreadPoolExecutor", return_value=executor) as factory:
        coordinator.submit("run-1", only_failed=False, runner="thread")
        coordinator.submit("run-2", only_failed=True, runner="thread")

    factory.assert_called_once_with(max_workers=1, thread_name_prefix="docai-run")
    assert executor.submit.call_count == 2


def test_local_coordinator_rejects_work_when_its_bounded_queue_is_full():
    coordinator = execution._LocalRunCoordinator(capacity=1)
    pending = MagicMock()
    executor = SimpleNamespace(submit=MagicMock(return_value=pending))

    with patch("docai.services.run_execution.ThreadPoolExecutor", return_value=executor):
        coordinator.submit("run-1", only_failed=False, runner="thread")
        with pytest.raises(RuntimeError, match="queue is full"):
            coordinator.submit("run-2", only_failed=False, runner="thread")

    pending.add_done_callback.assert_called_once()


def test_scheduled_local_execution_closes_database_connections():
    with (
        patch("docai.services.run_execution.close_old_connections") as close_connections,
        patch("docai.services.run_execution.execute_run") as execute,
    ):
        execution._execute_scheduled_local_run("run-1", only_failed=True, runner="thread")

    execute.assert_called_once_with(
        "run-1",
        only_failed=True,
        _scheduled_local=True,
        _runner="thread",
    )
    assert close_connections.call_count == 2


@pytest.mark.django_db
def test_local_queue_rejection_is_retryable_and_keeps_run_visible(
    project, dataset, admin, sample_workflow, w2_pdf
):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.create_run(project, sample_workflow, dataset, admin)

    with (
        patch.object(
            execution._local_run_coordinator,
            "submit",
            side_effect=RuntimeError("executor is shutting down"),
        ),
        pytest.raises(IntegrationError) as raised,
    ):
        execution.schedule_run(run.pk)

    run.refresh_from_db()
    assert raised.value.error_code == "EXECUTION_QUEUE_UNAVAILABLE"
    assert raised.value.headers == {"Retry-After": "2"}
    assert run.status == RUN_STATUS.running
    assert run.stage == "dispatch_failed"
    assert run.items.get().stage == "local_queued"


@pytest.mark.django_db
def test_celery_http_schedule_uses_per_item_dispatch_path(project, dataset, admin, sample_workflow):
    run = run_svc.create_run(project, sample_workflow, dataset, admin)
    celery_settings = {**settings.DOCAI, "TASK_RUNNER": "celery"}
    with (
        override_settings(DOCAI=celery_settings),
        patch("docai.services.run_execution.execute_run", return_value=run) as execute,
        patch.object(execution._local_run_coordinator, "submit") as local_submit,
    ):
        accepted = execution.schedule_run(run.pk, only_failed=True)

    assert accepted == run
    execute.assert_called_once_with(run.pk, only_failed=True)
    local_submit.assert_not_called()


@pytest.mark.django_db
def test_local_executor_failure_marks_unfinished_items_retryable(
    project, dataset, admin, sample_workflow, w2_pdf
):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.create_run(project, sample_workflow, dataset, admin)

    class FailingRunner:
        is_async = False

        def dispatch(self, *args, **kwargs):
            raise RuntimeError("executor stopped")

    with (
        patch("docai.services.run_execution._get_dispatcher", return_value=FailingRunner()),
        pytest.raises(IntegrationError) as raised,
    ):
        execution.execute_run(run.id)

    run.refresh_from_db()
    item = run.items.get()
    assert raised.value.error_code == "EXECUTION_INTERRUPTED"
    assert run.status == RUN_STATUS.failed
    assert run.stage == "finalized"
    assert item.status == ITEM_STATUS.failed
    assert item.stage == "execution_interrupted"
    assert item.error_code == "EXECUTION_INTERRUPTED"
    assert item.retryable is True


@pytest.mark.django_db
def test_cancelled_run_can_retry_its_failed_items(project, dataset, admin, sample_workflow, w2_pdf):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.create_run(project, sample_workflow, dataset, admin)
    run.status = RUN_STATUS.cancelled
    run.stage = "finalized"
    run.cancel_requested = True
    run.save(update_fields=["status", "stage", "cancel_requested", "status_changed", "modified"])
    item = run.items.get()
    item.status = ITEM_STATUS.failed
    item.retryable = True
    item.save(update_fields=["status", "retryable", "status_changed", "modified"])

    class CompletingRunner:
        is_async = False

        def dispatch(self, ids, **kwargs):
            del kwargs
            run.items.filter(pk__in=ids).update(status=ITEM_STATUS.succeeded)
            return False

    with patch("docai.services.run_execution._get_dispatcher", return_value=CompletingRunner()):
        retried = execution.execute_run(run.id, only_failed=True)

    assert retried.status == RUN_STATUS.succeeded
    assert retried.cancel_requested is False
    assert retried.failed_items == 0


@pytest.mark.django_db
def test_cancelling_queued_run_skips_work_and_finishes_immediately(
    project, dataset, admin, sample_workflow, w2_pdf
):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.create_run(project, sample_workflow, dataset, admin)

    cancelled = execution.request_cancel(run, admin)

    item = cancelled.items.get()
    assert cancelled.status == RUN_STATUS.cancelled
    assert cancelled.stage == "finalized"
    assert cancelled.cancel_requested is True
    assert cancelled.finished_at is not None
    assert item.status == ITEM_STATUS.skipped
    assert item.stage == "cancelled"


@pytest.mark.django_db
def test_cancelling_running_run_skips_only_unclaimed_work(
    project, dataset, admin, sample_workflow, w2_pdf, package_pdf
):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    ingestion.ingest_upload(dataset, package_pdf.filename, package_pdf.data, user=admin)
    run = run_svc.create_run(project, sample_workflow, dataset, admin)
    active, queued = list(run.items.order_by("created"))
    run.status = RUN_STATUS.running
    run.stage = "processing"
    run.save(update_fields=["status", "stage", "status_changed", "modified"])
    active.status = ITEM_STATUS.running
    active.stage = "workflow"
    active.save(update_fields=["status", "stage", "status_changed", "modified"])

    cancelling = execution.request_cancel(run, admin)

    active.refresh_from_db()
    queued.refresh_from_db()
    assert cancelling.status == RUN_STATUS.running
    assert cancelling.stage == "cancelling"
    assert cancelling.cancel_requested is True
    assert active.status == ITEM_STATUS.running
    assert queued.status == ITEM_STATUS.skipped

    active.status = ITEM_STATUS.succeeded
    active.stage = "done"
    active.save(update_fields=["status", "stage", "status_changed", "modified"])
    cancelled = execution.finalize_run(run.pk)
    assert cancelled.status == RUN_STATUS.cancelled
    assert cancelled.processed_items == 1


@pytest.mark.parametrize("pool", ["solo", "threads", "prefork"])
def test_celery_runner_publishes_independent_tasks_without_result_backend(pool):
    item_ids = [f"item-{index}" for index in range(5)]
    task_ids = {item_id: f"task-{index}" for index, item_id in enumerate(item_ids)}
    retry_policy = {"max_retries": 2}

    with (
        override_settings(
            CELERY_BROKER_URL="filesystem://",
            CELERY_RESULT_BACKEND=None,
            CELERY_TASK_PUBLISH_RETRY_POLICY=retry_policy,
            CELERY_WORKER_POOL=pool,
        ),
        patch("docai.tasks.celery_tasks.process_run_item.apply_async") as publish,
    ):
        scheduled = execution._CeleryDispatcher().dispatch(
            item_ids,
            run_id="run-one",
            task_ids=task_ids,
        )

    assert scheduled is True
    assert [call.kwargs["args"] for call in publish.call_args_list] == [
        [item_id] for item_id in item_ids
    ]
    assert [call.kwargs["task_id"] for call in publish.call_args_list] == list(task_ids.values())
    assert all(call.kwargs["retry_policy"] == retry_policy for call in publish.call_args_list)


def test_runtime_check_accepts_no_result_backend_and_validates_retry_limits():
    celery_settings = {**settings.DOCAI, "TASK_RUNNER": "celery"}
    with (
        override_settings(
            DOCAI=celery_settings,
            CELERY_BROKER_URL="filesystem://",
            CELERY_RESULT_BACKEND=None,
            CELERY_WORKER_POOL="prefork",
            CELERY_TASK_SOFT_TIME_LIMIT=30,
            CELERY_TASK_TIME_LIMIT=60,
            CELERY_TASK_MAX_RETRIES=3,
            CELERY_TASK_MAX_DELIVERIES=3,
            DEBUG=True,
        ),
        patch("docai.checks.importlib.util.find_spec", return_value=object()),
    ):
        issue_ids = {issue.id for issue in task_runtime_checks(None)}

    assert "docai.E004" not in issue_ids
    assert "docai.E010" in issue_ids


@pytest.mark.django_db
def test_celery_task_retries_only_a_retryable_recorded_failure(
    project, dataset, admin, sample_workflow, w2_pdf
):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.create_run(project, sample_workflow, dataset, admin)
    run.status = RUN_STATUS.running
    run.stage = "processing"
    run.save(update_fields=["status", "stage", "status_changed", "modified"])
    item = run.items.get()

    def recorded_failure(item_id, *, execution_id="", retry_retryable=False):
        assert str(item_id) == str(item.id)
        assert execution_id == "celery-task-id"
        assert retry_retryable is True
        run.items.filter(pk=item.id).update(
            status=ITEM_STATUS.queued,
            stage="retry_wait",
            retryable=True,
            error_code="UPSTREAM_THROTTLED",
            worker_task_id="celery-task-id",
        )
        return ITEM_STATUS.queued

    process_run_item.push_request(id="celery-task-id", retries=0)
    try:
        with (
            patch("docai.services.run_execution.process_item", side_effect=recorded_failure),
            patch.object(process_run_item, "retry", side_effect=Retry()) as retry,
            pytest.raises(Retry),
        ):
            process_run_item.run(str(item.id))
    finally:
        process_run_item.pop_request()

    item.refresh_from_db()
    assert item.status == ITEM_STATUS.queued
    assert item.stage == "retry_wait"
    assert retry.call_args.kwargs["max_retries"] == settings.CELERY_TASK_MAX_RETRIES
    assert 0 <= retry.call_args.kwargs["countdown"] <= settings.CELERY_TASK_RETRY_BACKOFF_SECONDS


def test_runtime_policy_derives_capacity_and_recovery_window():
    configured = SimpleNamespace(
        DOCAI={**settings.DOCAI, "TASK_RUNNER": "thread", "MAX_WORKERS": 8},
        DATABASES={"default": {"ENGINE": "django.db.backends.oracle"}},
        CELERY_TASK_TIME_LIMIT=1800,
        CELERY_TASK_RETRY_BACKOFF_MAX_SECONDS=600,
    )
    policy = current_task_runtime_policy(configured)

    assert policy.executor_capacity == 8
    assert policy.minimum_recovery_age_seconds == 1800


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("stale_status", "stale_stage", "expected_error"),
    [
        (ITEM_STATUS.running, "workflow", "WORKER_LOST"),
        (ITEM_STATUS.queued, "retry_wait", "WORKER_LOST"),
        (ITEM_STATUS.queued, "local_queued", "LOCAL_QUEUE_LOST"),
    ],
)
def test_stalled_worker_recovery_marks_item_retryable_and_finalizes_run(
    project,
    dataset,
    admin,
    sample_workflow,
    w2_pdf,
    stale_status,
    stale_stage,
    expected_error,
):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.create_run(project, sample_workflow, dataset, admin)
    run.status = RUN_STATUS.running
    run.stage = "processing"
    run.save(update_fields=["status", "stage", "status_changed", "modified"])
    item = run.items.get()
    item.status = stale_status
    item.stage = stale_stage
    item.save(update_fields=["status", "stage", "status_changed", "modified"])
    run.items.filter(pk=item.pk).update(
        status_changed=timezone.now() - timedelta(seconds=settings.CELERY_TASK_TIME_LIMIT + 600)
    )

    output = StringIO()
    call_command(
        "recover_stalled_runs",
        older_than_seconds=settings.CELERY_TASK_TIME_LIMIT + 300,
        stdout=output,
    )

    item.refresh_from_db()
    run.refresh_from_db()
    assert item.status == ITEM_STATUS.failed
    assert item.error_code == expected_error
    assert item.retryable is True
    assert run.status == RUN_STATUS.failed
    assert run.stage == "finalized"
    assert "Recovered 1 stalled item" in output.getvalue()
