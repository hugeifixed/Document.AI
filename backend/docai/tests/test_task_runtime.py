from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from config.celery_runtime import (
    default_filesystem_root,
    default_result_backend,
    default_worker_pool,
    ensure_filesystem_runtime,
    filesystem_path_error,
    filesystem_transport_options,
    projected_filesystem_path_length,
    worker_pool_error,
)
from docai.checks import task_runtime_checks
from docai.tasks.runner import CeleryRunner, ThreadRunner, get_runner


def test_platform_defaults_and_windows_pool_validation():
    assert default_worker_pool("Windows") == "threads"
    assert default_worker_pool("Darwin") == "prefork"
    assert default_worker_pool("Linux") == "prefork"
    assert worker_pool_error("threads", "Windows") is None
    assert worker_pool_error("solo", "Windows") is None
    assert "not supported on Windows" in worker_pool_error("prefork", "Windows")


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
    assert "C:\\docai-celery" in filesystem_path_error(long_root, "Windows")


def test_filesystem_broker_and_result_backend_share_created_runtime():
    with TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory) / "celery"
        options = filesystem_transport_options(root)
        paths = ensure_filesystem_runtime(root)

        assert options["data_folder_in"] == options["data_folder_out"]
        assert options["data_folder_in"] == str(paths["messages"])
        assert all(path.is_dir() for path in paths.values())
        assert default_result_backend("filesystem://", root) == paths["results"].as_uri()


def test_redis_broker_is_the_default_redis_result_backend():
    url = "redis://localhost:6379/0"
    assert default_result_backend(url, Path("unused")) == url


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
