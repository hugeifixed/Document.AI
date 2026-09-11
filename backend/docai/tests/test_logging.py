import io
import logging

import pytest
from django.test import override_settings
from loguru import logger

from docai.logging.context import reset_trace_id, set_trace_id
from docai.logging.middleware import _request_level
from docai.logging.setup import _console_format


@pytest.mark.django_db
def test_request_log_is_readable_and_correlated(client, admin):
    records = []
    client.force_login(admin)
    sink_id = logger.add(
        lambda message: records.append(message.record),
        level="DEBUG",
        filter=lambda record: record["extra"].get("event") == "http_request",
    )
    try:
        response = client.get("/api/v1/projects/", HTTP_X_REQUEST_ID="testrequest1234")
    finally:
        logger.remove(sink_id)

    record = records[-1]
    assert response.status_code == 200
    assert response["X-Request-ID"] == "testrequest1234"
    assert record["level"].name == "INFO"
    assert record["message"].startswith("GET /api/v1/projects/ 200 ")
    expected = {
        "event": "http_request",
        "method": "GET",
        "path": "/api/v1/projects/",
        "route": "project-list",
        "status": 200,
        "duration_ms": record["extra"]["duration_ms"],
        "user_id": str(admin.id),
        "exception_type": None,
        "trace_id": "testrequest1234",
    }
    assert {key: record["extra"][key] for key in expected} == expected


def test_console_format_shows_context_without_nested_loguru_metadata():
    output = io.StringIO()
    sink_id = logger.add(output, format=_console_format, colorize=False)
    try:
        logger.bind(
            event="http_request",
            method="GET",
            path="/api/v1/projects/",
            status=200,
            duration_ms=12.3,
            user_id="7",
            trace_id="abc123def456",
        ).info("GET /api/v1/projects/ 200 12.3ms")
    finally:
        logger.remove(sink_id)

    line = output.getvalue()
    assert "INFO    GET /api/v1/projects/ 200 12.3ms" in line
    assert "user=7 req=abc123def456" in line
    assert '"record"' not in line


def test_python_warnings_keep_the_active_request_id():
    records = []
    sink_id = logger.add(
        lambda message: records.append(message.record),
        filter=lambda record: record["message"] == "pagination warning",
    )
    token = set_trace_id("warningrequest123")
    try:
        logging.getLogger("py.warnings").warning("pagination warning")
    finally:
        reset_trace_id(token)
        logger.remove(sink_id)

    assert records[-1]["extra"]["trace_id"] == "warningrequest123"


@override_settings(DOCAI_SLOW_REQUEST_MS=1000)
@pytest.mark.parametrize(
    ("method", "path", "status", "duration_ms", "level"),
    [
        ("GET", "/api/v1/projects/", 200, 12, "INFO"),
        ("GET", "/api/v1/projects/", 404, 12, "WARNING"),
        ("POST", "/api/v1/runs/", 500, 12, "ERROR"),
        ("GET", "/api/v1/runs/", 200, 1200, "WARNING"),
        ("GET", "/health/", 200, 12, "DEBUG"),
        ("GET", "/admin/jsi18n/", 200, 12, "DEBUG"),
    ],
)
def test_request_level_highlights_failures_and_hides_probe_noise(
    method,
    path,
    status,
    duration_ms,
    level,
):
    assert _request_level(method, path, status, duration_ms) == level
