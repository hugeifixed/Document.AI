"""Offline coverage of worker startup logging and document processing milestones."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from textwrap import dedent
from threading import Barrier
from unittest.mock import patch

import pytest
from loguru import logger

from docai.exceptions import IntegrationError
from docai.logging.context import get_trace_id
from docai.models import ITEM_STATUS
from docai.services import ingestion, runs
from docai.tasks.celery_tasks import process_run_item


@pytest.fixture
def log_records():
    records = []
    sink = logger.add(lambda message: records.append(message.record), level="DEBUG")
    try:
        yield records
    finally:
        logger.remove(sink)


@pytest.mark.parametrize(
    ("json_output", "level"), [(False, "INFO"), (True, "INFO"), (False, "DEBUG")]
)
def test_celery_setup_uses_redacted_sinks_and_respects_cli_level(tmp_path, json_output, level):
    # A fresh process exercises the real Celery setup signal without changing pytest's
    # logging handlers, connecting to a broker, or creating a document processing job.
    script = dedent("""
        import logging
        import sys
        from pathlib import Path
        import django
        django.setup()
        from django.conf import settings
        from celery.utils.log import get_task_logger
        from config.celery import app
        from docai.logging.context import set_trace_id
        from loguru import logger

        settings.DOCAI_LOG_JSON = sys.argv[1] == 'True'
        settings.DOCAI_LOG_DIR = Path(sys.argv[3])
        app.log.setup(loglevel=sys.argv[2], colorize=False)
        task_logger = get_task_logger('docai.logging.probe')

        @app.task(name='docai.logging.probe')
        def probe():
            set_trace_id('workerrequestabcd')
            task_logger.warning('credential token=private-value')
            logging.getLogger('httpx').info('transport-success')
            logging.getLogger('httpx').warning('transport-warning')

        probe.apply(task_id='a62f11e4-cbbd-4ac7-abcd-abcdabcdabcd', throw=True)
        logging.getLogger('celery.worker').error('worker-lost')
        try:
            raise RuntimeError('token=private-value')
        except RuntimeError:
            logging.getLogger('celery.worker').exception('worker-exception')
        logger.info('outside-task')
        logger.complete()
    """)
    result = subprocess.run(  # noqa: S603 -- fixed offline script and pytest-owned paths
        [sys.executable, "-c", script, str(json_output), level, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    output = result.stdout + result.stderr
    assert "private-value" not in output
    assert "\x1b[" not in output  # Non-TTY output stays usable when piped.
    assert output.count("credential token=[REDACTED]") == 1
    assert output.count("transport-warning") == 1
    assert output.count("worker-lost") == 1
    assert ("transport-success" in output) is (level == "DEBUG")
    assert ("succeeded in" in output) is (level == "DEBUG")
    if json_output:
        records = [json.loads(line) for line in result.stdout.splitlines()]
        credential = next(
            record for record in records if record["message"].startswith("credential")
        )
        assert credential["task_id"] == "a62f11e4-cbbd-4ac7-abcd-abcdabcdabcd"
        assert credential["task_name"] == "docai.logging.probe"
        assert credential["trace_id"] == "workerrequestabcd"
        assert credential["stdlib_logger"] == "docai.logging.probe"
        assert "task_id" not in next(
            record for record in records if record["message"] == "outside-task"
        )
    else:
        assert "W probe[a62f11e4] | credential token=[REDACTED]" in output
        assert "E MainProcess | worker-lost" in output
        assert "I MainProcess | outside-task" in output
    stored = [json.loads(line) for line in (tmp_path / "docai.log").read_text().splitlines()]
    assert any(record.get("task_id") == "a62f11e4-cbbd-4ac7-abcd-abcdabcdabcd" for record in stored)


@pytest.mark.django_db
def test_document_milestones_are_correlated_and_cache_reuse_is_honest(
    dataset, project, admin, sample_workflow, w2_pdf, settings, tmp_path, log_records
):
    settings.MEDIA_ROOT = tmp_path
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = runs.create_run(project, sample_workflow, dataset, admin)
    item = run.items.get()
    trace_before = get_trace_id()
    task_id = "a62f11e4-cbbd-4ac7-abcd-abcdabcdabcd"
    result = process_run_item.apply(args=[str(item.pk)], task_id=task_id, throw=True)
    assert result.result == ITEM_STATUS.succeeded
    events = [record for record in log_records if record["extra"].get("event")]
    names = [record["extra"]["event"] for record in events]
    assert names.index("processing_started") < names.index("layout_started")
    assert names.index("layout_completed") < names.index("llm_stage_started")
    assert names.index("chunking_completed") < names.index("processing_completed")
    for record in events:
        assert record["extra"]["task_id"] == task_id
        assert record["extra"]["item_id"] == str(item.pk)
        assert record["extra"]["run_id"] == str(run.pk)
        assert record["extra"]["document_id"] == str(item.document_id)
        assert record["extra"]["trace_id"]
        assert record["extra"]["attempt"] == 1
    layout = next(record for record in events if record["extra"]["event"] == "layout_completed")
    assert layout["message"] == "Layout reading completed"
    assert layout["extra"]["pages"] > 0
    assert layout["extra"]["chars"] > 0
    stages = [
        record["extra"]["stage"]
        for record in events
        if record["extra"]["event"] == "llm_stage_started"
    ]
    assert len(stages) == len(set(stages))
    assert get_trace_id() == trace_before
    logger.info("outside-document")
    assert "item_id" not in log_records[-1]["extra"]
    assert "task_id" not in log_records[-1]["extra"]

    log_records.clear()
    next_run = runs.create_run(project, sample_workflow, dataset, admin)
    next_item = next_run.items.get()
    process_run_item.apply(args=[str(next_item.pk)], throw=True)
    names = [record["extra"].get("event") for record in log_records]
    assert "layout_reused" in names
    assert "layout_started" not in names
    assert "normalization_started" not in names


@pytest.mark.django_db
@pytest.mark.parametrize("retryable", [False, True])
def test_processing_failure_reports_stage_and_retry_without_success(
    dataset, project, admin, sample_workflow, w2_pdf, settings, tmp_path, log_records, retryable
):
    from celery.exceptions import Retry

    settings.MEDIA_ROOT = tmp_path
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = runs.create_run(project, sample_workflow, dataset, admin)
    item = run.items.get()
    error = IntegrationError(
        "upstream unavailable",
        error_code="AZURE_429" if retryable else "AZURE_404",
        retryable=retryable,
        diagnostics={
            "exception_type": "APIStatusError",
            "upstream_status": 429 if retryable else 404,
            "provider_request_id": "provider-request-1",
        },
    )
    process_run_item.push_request(id="task-failure-abcd", retries=0)
    try:
        with (
            patch("docai.services.run_execution.get_or_build_layout", side_effect=error),
            patch.object(process_run_item, "retry", side_effect=Retry()) as retry,
        ):
            if retryable:
                with pytest.raises(Retry):
                    process_run_item.run(str(item.pk))
            else:
                assert process_run_item.run(str(item.pk)) == ITEM_STATUS.failed
                retry.assert_not_called()
    finally:
        process_run_item.pop_request()
    failures = [
        record for record in log_records if record["extra"].get("event") == "processing_failed"
    ]
    assert len(failures) == 1
    assert failures[0]["level"].name == ("WARNING" if retryable else "ERROR")
    assert failures[0]["extra"]["stage"] == "layout"
    assert failures[0]["extra"]["error_code"] == error.error_code
    assert failures[0]["extra"]["retry_pending"] is retryable
    assert failures[0]["extra"]["duration_ms"] >= 0
    assert failures[0]["extra"]["exception_type"] == "APIStatusError"
    assert failures[0]["extra"]["provider_request_id"] == "provider-request-1"
    assert failures[0]["extra"]["reason"] == "upstream unavailable"
    assert not any(record["extra"].get("event") == "processing_completed" for record in log_records)
    logger.info("after-failure")
    assert "item_id" not in log_records[-1]["extra"]


def test_task_context_is_isolated_between_worker_threads(log_records):
    barrier = Barrier(2)

    def deliver(item_id, *, task_id, retries):
        assert item_id == task_id
        barrier.wait(timeout=5)
        logger.info("thread-delivery")
        return type("Delivery", (), {"status": ITEM_STATUS.running, "retry": False})()

    def run_task(item_id):
        process_run_item.push_request(id=item_id, retries=0)
        try:
            process_run_item.run(item_id)
            logger.info("thread-outside-task")
        finally:
            process_run_item.pop_request()

    with (
        patch("docai.services.run_execution.process_celery_delivery", side_effect=deliver),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        list(pool.map(run_task, ["task-alpha", "task-beta"]))
    records = [record for record in log_records if record["message"] == "thread-delivery"]
    assert {record["extra"]["task_id"] for record in records} == {"task-alpha", "task-beta"}
    assert all(record["extra"]["task_id"] == record["extra"]["item_id"] for record in records)
    assert all(
        "task_id" not in record["extra"]
        for record in log_records
        if record["message"] == "thread-outside-task"
    )


@pytest.mark.django_db
def test_unexpected_processing_failure_is_visible_without_exception_payload(
    dataset, project, admin, sample_workflow, w2_pdf, settings, tmp_path, log_records
):
    settings.MEDIA_ROOT = tmp_path
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = runs.create_run(project, sample_workflow, dataset, admin)
    item = run.items.get()
    log_records.clear()
    with patch(
        "docai.services.run_execution.get_or_build_layout",
        side_effect=RuntimeError("private-document-value"),
    ):
        result = process_run_item.apply(args=[str(item.pk)], task_id="unexpected-task", throw=True)
    assert result.result == ITEM_STATUS.failed
    failure = next(r for r in log_records if r["extra"].get("event") == "processing_failed")
    assert failure["level"].name == "ERROR"
    assert failure["extra"]["exception_type"] == "RuntimeError"
    assert "process_item" in failure["extra"]["error_stack"]
    assert failure["extra"]["stage"] == "layout"
    assert failure["extra"]["task_id"] == "unexpected-task"
    assert "private-document-value" not in str([(r["message"], r["extra"]) for r in log_records])


@pytest.mark.django_db
def test_api_access_log_includes_handled_error_code_and_type(api, log_records):
    response = api.post("/api/v1/workflows/validate/", {}, format="json")
    assert response.status_code == 422
    record = next(r for r in log_records if r["extra"].get("event") == "http_request")
    assert record["extra"]["error_code"] == "VALIDATION_ERROR"
    assert record["extra"]["exception_type"] == "ValidationError"
    assert record["extra"]["trace_id"] == response["X-Request-ID"]
