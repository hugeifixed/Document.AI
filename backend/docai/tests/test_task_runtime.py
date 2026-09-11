from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import get_ident
from unittest.mock import patch

import pytest
from celery.exceptions import Retry
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from config.celery_runtime import (
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
from docai.services import runs as run_svc
from docai.tasks.celery_tasks import process_run_item
from docai.tasks.runner import CeleryRunner, ThreadRunner, get_runner


def test_platform_defaults_and_windows_pool_validation():
    assert default_worker_pool("Windows") == "threads"
    assert default_worker_pool("Darwin") == "prefork"
    assert default_worker_pool("Linux") == "prefork"
    assert worker_pool_error("threads", "Windows") is None
    assert worker_pool_error("solo", "Windows") is None
    prefork_error = worker_pool_error("prefork", "Windows")
    assert prefork_error is not None and "not supported on Windows" in prefork_error


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


def test_runtime_check_rejects_windows_prefork():
    celery_settings = {**settings.DOCAI, "TASK_RUNNER": "celery"}
    with (
        override_settings(
            DOCAI=celery_settings,
            CELERY_BROKER_URL="filesystem://",
            CELERY_RESULT_BACKEND="file:///tmp/results",
            CELERY_WORKER_POOL="prefork",
            DEBUG=True,
        ),
        patch("docai.checks.platform.system", return_value="Windows"),
        patch("docai.checks.importlib.util.find_spec", return_value=object()),
    ):
        issue_ids = {issue.id for issue in task_runtime_checks(None)}

    assert "docai.E005" in issue_ids
    assert "docai.W001" in issue_ids


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
        patch("docai.checks.platform.system", return_value="Windows"),
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
        patch("docai.checks.platform.system", return_value="Windows"),
        patch("docai.checks.importlib.util.find_spec", side_effect=installed_module),
    ):
        issue_ids = {issue.id for issue in task_runtime_checks(None)}

    assert "docai.E007" in issue_ids


def test_runner_selection_has_clear_configuration_error():
    with override_settings(DOCAI={**settings.DOCAI, "TASK_RUNNER": "unknown"}):
        try:
            get_runner()
        except ImproperlyConfigured as exc:
            assert "sync, thread, or celery" in str(exc)
        else:  # pragma: no cover - makes a missing exception an explicit failure
            raise AssertionError("Expected ImproperlyConfigured")


def test_runner_execution_modes_are_explicit():
    assert ThreadRunner.is_async is False
    assert CeleryRunner.is_async is True


def test_thread_runner_executes_inline_with_sqlite(monkeypatch):
    calls: list[str] = []
    monkeypatch.setitem(settings.DATABASES["default"], "ENGINE", "django.db.backends.sqlite3")

    with patch("docai.tasks.runner.ThreadPoolExecutor") as executor:
        scheduled = ThreadRunner().map(calls.append, ["one", "two"])

    assert scheduled is False
    assert calls == ["one", "two"]
    executor.assert_not_called()


def test_thread_runner_keeps_thread_pool_for_server_databases(monkeypatch):
    caller = get_ident()
    worker_threads: list[int] = []
    monkeypatch.setitem(settings.DATABASES["default"], "ENGINE", "django.db.backends.postgresql")

    scheduled = ThreadRunner().map(lambda _: worker_threads.append(get_ident()), ["one"])

    assert scheduled is False
    assert worker_threads and worker_threads[0] != caller


@pytest.mark.django_db
def test_local_executor_failure_marks_unfinished_items_retryable(
    project, dataset, admin, sample_workflow, w2_pdf
):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.create_run(project, sample_workflow, dataset, admin)

    class FailingRunner:
        is_async = False

        def map(self, *args, **kwargs):
            raise RuntimeError("executor stopped")

    with (
        patch("docai.tasks.runner.get_runner", return_value=FailingRunner()),
        pytest.raises(IntegrationError) as raised,
    ):
        run_svc.execute_run(run.id)

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

        def map(self, fn, ids, **kwargs):
            del fn, kwargs
            run.items.filter(pk__in=ids).update(status=ITEM_STATUS.succeeded)
            return False

    with patch("docai.tasks.runner.get_runner", return_value=CompletingRunner()):
        retried = run_svc.execute_run(run.id, only_failed=True)

    assert retried.status == RUN_STATUS.succeeded
    assert retried.cancel_requested is False
    assert retried.failed_items == 0


@pytest.mark.django_db
def test_cancelling_queued_run_skips_work_and_finishes_immediately(
    project, dataset, admin, sample_workflow, w2_pdf
):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.create_run(project, sample_workflow, dataset, admin)

    cancelled = run_svc.request_cancel(run, admin)

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

    cancelling = run_svc.request_cancel(run, admin)

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
    cancelled = run_svc.finalize_run(run.pk)
    assert cancelled.status == RUN_STATUS.cancelled
    assert cancelled.processed_items == 1


def test_celery_runner_publishes_independent_tasks_without_result_backend():
    item_ids = ["item-one", "item-two"]
    task_ids = {"item-one": "task-one", "item-two": "task-two"}
    retry_policy = {"max_retries": 2}

    with (
        override_settings(
            CELERY_BROKER_URL="filesystem://",
            CELERY_RESULT_BACKEND=None,
            CELERY_TASK_PUBLISH_RETRY_POLICY=retry_policy,
            CELERY_WORKER_POOL="solo",
        ),
        patch("docai.tasks.celery_tasks.process_run_item.apply_async") as publish,
    ):
        scheduled = CeleryRunner().map(
            lambda item_id: item_id,
            item_ids,
            run_id="run-one",
            task_ids=task_ids,
        )

    assert scheduled is True
    assert [call.kwargs["args"] for call in publish.call_args_list] == [["item-one"], ["item-two"]]
    assert [call.kwargs["task_id"] for call in publish.call_args_list] == ["task-one", "task-two"]
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
            patch("docai.services.runs.process_item", side_effect=recorded_failure),
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


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("stale_status", "stale_stage"),
    [
        (ITEM_STATUS.running, "workflow"),
        (ITEM_STATUS.queued, "retry_wait"),
    ],
)
def test_stalled_worker_recovery_marks_item_retryable_and_finalizes_run(
    project, dataset, admin, sample_workflow, w2_pdf, stale_status, stale_stage
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
    assert item.error_code == "WORKER_LOST"
    assert item.retryable is True
    assert run.status == RUN_STATUS.failed
    assert run.stage == "finalized"
    assert "Recovered 1 stalled item" in output.getvalue()
