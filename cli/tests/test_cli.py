from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from typing import Any

import pytest
import requests
from typer.testing import CliRunner

from docai_cli import __version__
from docai_cli.client import DocAIClient
from docai_cli.errors import (
    EXIT_AUTH,
    EXIT_NOT_FOUND,
    EXIT_TIMEOUT,
    EXIT_TRANSPORT,
    EXIT_VALIDATION,
    CliError,
)
from docai_cli.main import _normalize_global_options, app, main
from docai_cli.output import (
    emit_detail,
    emit_human_error,
    emit_json,
    emit_rows,
    emit_run_completion,
)


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        data: Any = None,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
    ) -> None:
        self.status_code = status
        self.headers = headers or {}
        self._data = data
        self.content = body
        self.ok = status < 400
        self.closed = False

    def json(self):
        if self._data is None:
            raise ValueError("not JSON")
        return self._data

    def iter_content(self, chunk_size=1):
        del chunk_size
        yield self.content

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.cookies: dict[str, str] = {"csrftoken": "csrf-value"}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.trust_env = True
        self.proxies = {}
        self.verify = True
        self.auth = None
        self.closed = False

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"Unexpected request {method} {url}")
        return self.responses.pop(0)

    def post(self, url: str, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0) if self.responses else FakeResponse()

    def close(self):
        self.closed = True


def client_with(monkeypatch, responses=None, **kwargs):
    from docai_cli import client as client_module

    session = FakeSession(responses)
    monkeypatch.setattr(client_module.requests, "Session", lambda: session)
    return DocAIClient("https://docai.example", **kwargs), session


def envelope(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data, "trace_id": "trace-123"}


def test_cli_import_boundary_has_no_django_imports():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import docai_cli.main; "
            "assert not any(name == 'django' or name.startswith('django.') for name in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_cli_help_discovers_workflow_and_run_commands():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "projects" in result.output
    assert "runs" in result.output
    assert "documents" in result.output
    assert app.pretty_exceptions_enable is False
    assert app.pretty_exceptions_show_locals is False


@pytest.mark.parametrize(
    "command",
    [
        ["health"],
        ["auth", "status"],
        ["projects", "list"],
        ["datasets", "list"],
        ["workflows", "list"],
        ["workflows", "contract"],
        ["documents", "list"],
        ["documents", "upload"],
        ["runs", "submit"],
        ["runs", "list"],
        ["runs", "show"],
        ["runs", "progress"],
        ["runs", "wait"],
        ["runs", "cancel"],
        ["runs", "retry"],
        ["runs", "export"],
        ["review", "list"],
    ],
)
def test_documented_commands_have_help(command):
    result = CliRunner().invoke(app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output


def test_cli_version_works_without_a_subcommand():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == f"docai {__version__}"


def test_json_usage_error_is_a_single_structured_object(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["docai", "documents", "list", "--json"])

    with pytest.raises(SystemExit) as captured:
        main()

    out, err = capsys.readouterr()
    assert captured.value.code == 2
    assert err == ""
    payload = json.loads(out)
    assert payload["error"] == {
        "code": "CLI_USAGE_ERROR",
        "message": "Invalid or missing value for 'dataset'.",
    }
    assert payload["operation"] == {"parameter": "dataset", "option": None}


def test_human_usage_error_stays_on_stderr(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["docai", "documents", "list"])

    with pytest.raises(SystemExit) as captured:
        main()

    out, err = capsys.readouterr()
    assert captured.value.code == 2
    assert out == ""
    assert "Missing option '--dataset'" in err


def test_shared_json_flag_can_follow_command_without_stealing_option_value():
    assert _normalize_global_options(["projects", "list", "--json"]) == [
        "--json",
        "projects",
        "list",
    ]
    assert _normalize_global_options(["runs", "submit", "--name", "--json"]) == [
        "runs",
        "submit",
        "--name",
        "--json",
    ]
    assert _normalize_global_options(["runs", "export", "--output", "--json"]) == [
        "runs",
        "export",
        "--output",
        "--json",
    ]
    assert _normalize_global_options(["documents", "upload", "--", "--json"]) == [
        "documents",
        "upload",
        "--",
        "--json",
    ]


def test_global_flags_and_values_move_before_the_nested_command():
    assert _normalize_global_options(
        ["projects", "list", "--json", "--base-url", "https://docai.example"]
    ) == ["--json", "--base-url", "https://docai.example", "projects", "list"]


def test_json_output_is_one_compact_object_with_stable_key_order(capsys):
    emit_json(data={"id": "full-uuid"})
    out, err = capsys.readouterr()
    payload = json.loads(out)
    assert err == ""
    assert list(payload) == [
        "success",
        "data",
        "error",
        "trace_id",
        "operation",
        "retryable",
        "cli_version",
    ]
    assert payload["cli_version"] == __version__
    assert out.count("\n") == 1
    assert "\\u" not in out


def test_human_details_are_readable_and_json_keeps_original_timestamps(capsys):
    data = {
        "run_id": "full-run-id",
        "created": "2026-09-25T12:00:36.720000Z",
        "progress": {"processed_items": 2, "updated_at": "2026-09-25T12:01:00Z"},
    }

    emit_detail(data, json_mode=False, utc=True)
    human, err = capsys.readouterr()
    assert err == ""
    assert json.loads(human) == {
        "run_id": "full-run-id",
        "created": "2026-09-25 12:00",
        "progress": {"processed_items": 2, "updated_at": "2026-09-25 12:01"},
    }
    assert "'processed_items':" not in human

    emit_detail(data, json_mode=True, utc=True)
    agent, err = capsys.readouterr()
    assert err == ""
    assert agent.count("\n") == 1
    assert json.loads(agent)["data"] == data


def test_tty_details_keep_full_ids_without_color_when_requested(monkeypatch):
    from docai_cli import output

    capture = io.StringIO()
    capture.isatty = lambda: True  # type: ignore[attr-defined]
    monkeypatch.setattr(output.sys, "stdout", capture)
    monkeypatch.setattr(output, "shutil_terminal_width", lambda: 100)
    identifier = "ef7ea548-a18a-4bcb-9c2b-7df9d675f472"

    output.emit_detail(
        {"run_id": identifier, "status": "succeeded"}, json_mode=False, no_color=True
    )

    assert json.loads(capture.getvalue())["run_id"] == identifier
    assert "\x1b" not in capture.getvalue()


def test_piped_human_rows_are_tsv_and_keep_full_uuids(capsys, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    identifier = "12345678-1234-4234-8234-123456789abc"
    emit_rows(
        [{"name": "A very long name", "id": identifier}], json_mode=False, columns=("name", "id")
    )
    out, _ = capsys.readouterr()
    assert out.strip() == f"A very long name\t{identifier}"


def test_id_only_emits_complete_ids(capsys):
    emit_rows([{"id": "a-very-long-uuid-value"}], json_mode=False, id_only=True)
    out, _ = capsys.readouterr()
    assert out == "a-very-long-uuid-value\n"


def test_json_id_only_returns_only_full_ids(capsys):
    emit_rows([{"id": "full-uuid", "name": "hidden"}], json_mode=True, id_only=True)
    out, _ = capsys.readouterr()
    assert json.loads(out)["data"] == ["full-uuid"]


def test_session_auth_fetches_csrf_and_attempts_logout(monkeypatch):
    responses = [
        FakeResponse(data=envelope({"user": None})),
        FakeResponse(data=envelope({"user": {}})),
    ]
    client, session = client_with(monkeypatch, responses, username="operator", password="secret")
    client.authenticate()
    assert session.calls[0][0:2] == ("GET", "https://docai.example/api/v1/auth/session/")
    method, url, kwargs = session.calls[1]
    assert (method, url) == ("POST", "https://docai.example/api/v1/auth/login/")
    assert kwargs["headers"]["X-CSRFToken"] == "csrf-value"
    assert kwargs["json"] == {"username": "operator", "password": "secret"}
    client.close()
    assert session.calls[-1][1].endswith("/auth/logout/")
    assert session.closed


def test_basic_auth_requires_username_and_never_uses_netrc(monkeypatch):
    client, session = client_with(
        monkeypatch, username="agent", password="secret", auth_mode="basic"
    )
    client.authenticate()
    assert session.auth == ("agent", "secret")
    assert session.trust_env is False
    assert client.session.verify is True
    client.close()


def test_missing_password_in_noninteractive_process_fails_without_prompt(monkeypatch):
    client, _ = client_with(monkeypatch, username="agent", auth_mode="basic")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(CliError) as captured:
        client.authenticate()
    assert captured.value.exit_code == EXIT_AUTH
    assert captured.value.error_code == "PASSWORD_REQUIRED"


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, EXIT_AUTH), (403, EXIT_AUTH), (404, EXIT_NOT_FOUND), (422, EXIT_VALIDATION), (500, 6)],
)
def test_api_status_maps_to_stable_exit_codes(monkeypatch, status, expected):
    payload = {"success": False, "error_code": "SAMPLE", "message": "bad", "trace_id": "t-1"}
    client, _ = client_with(
        monkeypatch,
        [FakeResponse(status=status, data=payload)],
        username="u",
        password="p",
        auth_mode="basic",
    )
    client._authenticated = True
    with pytest.raises(CliError) as captured:
        client.get_json("projects/")
    assert captured.value.exit_code == expected
    assert captured.value.trace_id == "t-1"


def test_partial_upload_error_retains_accepted_and_rejected_details(monkeypatch, tmp_path):
    data = {
        "accepted": [{"id": "doc-1"}],
        "reused_document_ids": [],
        "rejected": [{"filename": "bad.exe", "error_code": "UNSUPPORTED_FILE_TYPE"}],
    }
    payload = {"success": True, "message": "1 rejected", "data": data}
    client, _ = client_with(
        monkeypatch,
        [FakeResponse(status=422, data=payload)],
        username="u",
        password="p",
        auth_mode="basic",
    )
    client._authenticated = True
    source = tmp_path / "bad.exe"
    source.write_bytes(b"data")
    with pytest.raises(CliError) as captured:
        client.upload("dataset-1", [source])
    assert captured.value.exit_code == EXIT_VALIDATION
    assert captured.value.data == data


def test_partial_upload_reports_ids_and_reasons_to_humans_and_agents(monkeypatch, tmp_path):
    data = {
        "accepted": [{"id": "full-document-uuid", "original_filename": "w2.pdf"}],
        "reused_document_ids": ["full-document-uuid"],
        "rejected": [
            {
                "filename": "note.exe",
                "error_code": "UNSUPPORTED_FILE_TYPE",
                "message": "This file type is not supported.",
            }
        ],
    }

    def reject_upload(self, dataset_id, paths, *, on_progress=None):
        del self, dataset_id, paths, on_progress
        raise CliError(
            "One or more files were rejected.",
            EXIT_VALIDATION,
            "PARTIAL_UPLOAD_REJECTION",
            trace_id="trace-upload",
            data=data,
        )

    monkeypatch.setattr(DocAIClient, "upload", reject_upload)
    source = tmp_path / "note.exe"
    source.write_bytes(b"input")
    args = ["documents", "upload", "--dataset", "dataset-1", str(source)]

    human = CliRunner().invoke(app, args)
    assert human.exit_code == EXIT_VALIDATION
    assert human.stdout == ""
    assert "full-document-uuid" in human.stderr
    assert "w2.pdf" in human.stderr
    assert "reused" in human.stderr
    assert "This file type is not supported." in human.stderr
    assert "trace-upload" in human.stderr

    agent = CliRunner().invoke(app, ["--json", *args])
    assert agent.exit_code == EXIT_VALIDATION
    assert agent.stderr == ""
    assert agent.stdout.count("\n") == 1
    payload = json.loads(agent.stdout)
    assert payload["data"] == data
    assert payload["error"]["code"] == "PARTIAL_UPLOAD_REJECTION"


def test_success_status_with_partial_upload_rejection_is_not_reported_as_success(
    monkeypatch, tmp_path
):
    data = {
        "accepted": [{"id": "doc-1"}],
        "reused_document_ids": [],
        "rejected": [{"filename": "bad.exe", "error_code": "UNSUPPORTED_FILE_TYPE"}],
    }
    body = {"success": True, "message": "1 rejected", "data": data, "trace_id": "trace-1"}
    client, _ = client_with(
        monkeypatch,
        [FakeResponse(status=201, data=body)],
        username="u",
        password="p",
        auth_mode="basic",
    )
    client._authenticated = True
    source = tmp_path / "bad.exe"
    source.write_bytes(b"data")

    with pytest.raises(CliError) as captured:
        client.upload("dataset-1", [source])

    assert captured.value.exit_code == EXIT_VALIDATION
    assert captured.value.error_code == "PARTIAL_UPLOAD_REJECTION"
    assert captured.value.trace_id == "trace-1"
    assert captured.value.data == data


def test_pagination_follows_same_origin_next_links(monkeypatch):
    pages = [
        FakeResponse(
            data=envelope(
                {
                    "results": [{"id": "one"}],
                    "next": "https://docai.example/api/v1/projects/?page=2",
                }
            )
        ),
        FakeResponse(data=envelope({"results": [{"id": "two"}], "next": None})),
    ]
    client, session = client_with(monkeypatch, pages, username="u", password="p", auth_mode="basic")
    client._authenticated = True
    rows = client.list_all("projects/", all_pages=True, limit=1)
    assert [row["id"] for row in rows] == ["one", "two"]
    assert len(session.calls) == 2
    assert session.calls[1][1].endswith("projects/?page=2")


def test_pagination_appends_page_parameters_to_existing_filters(monkeypatch):
    client, session = client_with(
        monkeypatch,
        [FakeResponse(data=envelope({"results": [], "next": None}))],
        username="u",
        password="p",
        auth_mode="basic",
    )
    client._authenticated = True

    assert client.list_all("datasets/?project=project%2Fone", page=2, limit=10) == []

    assert session.calls[0][1].endswith("datasets/?project=project%2Fone&page=2&page_size=10")


def test_pagination_refuses_foreign_next_link(monkeypatch):
    client, _ = client_with(
        monkeypatch,
        [FakeResponse(data=envelope({"results": [], "next": "https://attacker.example/steal"}))],
        username="u",
        password="p",
        auth_mode="basic",
    )
    client._authenticated = True
    with pytest.raises(CliError, match="different host"):
        client.list_all("projects/", all_pages=True)


def test_list_limit_is_bounded_by_api_contract(monkeypatch):
    client, _ = client_with(monkeypatch, username="u", password="p", auth_mode="basic")
    with pytest.raises(CliError) as captured:
        client.list_all("projects/", limit=201)
    assert captured.value.error_code == "INVALID_LIMIT"


def test_poll_response_supports_not_modified_without_losing_etag(monkeypatch):
    client, session = client_with(
        monkeypatch,
        [FakeResponse(status=304, headers={"Retry-After": "2"})],
        username="u",
        password="p",
        auth_mode="basic",
    )
    client._authenticated = True
    data, response = client.get_json("runs/run-id/results/", headers={"If-None-Match": 'W/"v1"'})
    assert data is None
    assert response.status_code == 304
    assert session.calls[0][2]["headers"] == {"If-None-Match": 'W/"v1"'}


def test_export_publishes_complete_file_without_overwriting(monkeypatch, tmp_path):
    client, _ = client_with(
        monkeypatch,
        [FakeResponse(body=b"complete export")],
        username="u",
        password="p",
        auth_mode="basic",
    )
    client._authenticated = True
    output = tmp_path / "result.json"
    client.download("runs/run-1/export/json/", output)
    assert output.read_bytes() == b"complete export"
    with pytest.raises(CliError, match="already exists"):
        client.download("runs/run-1/export/json/", output)


def test_base_url_requires_https_except_local_development(monkeypatch):
    client, _ = client_with(monkeypatch)
    client.close()
    with pytest.raises(CliError, match="HTTPS"):
        DocAIClient("http://docai.example")


def test_redirects_are_refused_without_following_or_forwarding_credentials(monkeypatch):
    client, session = client_with(
        monkeypatch,
        [FakeResponse(status=307, headers={"Location": "https://attacker.example/login"})],
        username="operator",
        password="secret",
        auth_mode="basic",
    )
    client._authenticated = True

    with pytest.raises(CliError) as captured:
        client.get_json("projects/")

    assert captured.value.error_code == "UNEXPECTED_REDIRECT"
    assert captured.value.exit_code == EXIT_VALIDATION
    assert len(session.calls) == 1
    assert session.calls[0][2]["allow_redirects"] is False


def test_session_authentication_refuses_redirect_response(monkeypatch):
    client, session = client_with(
        monkeypatch,
        [FakeResponse(status=302, headers={"Location": "http://attacker.example/"})],
        username="operator",
        password="secret",
    )

    with pytest.raises(CliError) as captured:
        client.authenticate()

    assert captured.value.error_code == "UNEXPECTED_REDIRECT"
    assert len(session.calls) == 1
    assert session.calls[0][2]["allow_redirects"] is False


def test_invalid_session_credentials_use_authentication_exit_code(monkeypatch):
    client, session = client_with(
        monkeypatch,
        [
            FakeResponse(data=envelope({"user": None})),
            FakeResponse(
                status=400,
                data={
                    "success": False,
                    "error": {
                        "error_code": "INVALID_CREDENTIALS",
                        "message": "Username or password is incorrect.",
                    },
                },
            ),
        ],
        username="operator",
        password="incorrect",
        auth_mode="session",
    )

    with pytest.raises(CliError) as captured:
        client.get_json("projects/")

    assert captured.value.error_code == "INVALID_CREDENTIALS"
    assert captured.value.exit_code == EXIT_AUTH
    assert [call[0] for call in session.calls] == ["GET", "POST"]
    assert session.calls[1][2]["allow_redirects"] is False


def test_human_timestamps_use_local_time_or_explicit_utc(capsys, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    rows = [{"created": "2026-09-25T12:00:00Z", "id": "run-1"}]
    emit_rows(rows, json_mode=False, columns=("created", "id"), utc=True)
    out, _ = capsys.readouterr()
    assert out == "2026-09-25 12:00\trun-1\n"


def test_cli_commands_are_covered_by_help_and_callable_routes(monkeypatch, tmp_path):
    from docai_cli.client import DocAIClient

    def get_json(self, path, *, api=True, headers=None):
        del self, api, headers
        if path.startswith("runs/") and path.endswith("/results/"):
            data = {"run_id": "run-1", "status": "succeeded", "completed": True}
        else:
            data = {"user": {"username": "operator"}}
        return data, FakeResponse(data=envelope(data))

    def list_all(self, path, **kwargs):
        del self, path, kwargs
        return [{"id": "record-1", "name": "Sample", "status": "approved"}]

    def post_json(self, path, payload, *, headers=None):
        del self, payload, headers
        return {"run_id": "run-1", "links": {}}, FakeResponse(data=envelope({"run_id": "run-1"}))

    def upload(self, dataset_id, paths, *, on_progress=None):
        del self, dataset_id, paths, on_progress
        return {"accepted": [{"id": "document-1"}], "rejected": []}, FakeResponse()

    def download(self, path, destination, *, force=False, on_progress=None):
        del self, path, force, on_progress
        destination.write_text("export", encoding="utf-8")

    monkeypatch.setattr(
        DocAIClient, "authenticate", lambda self: setattr(self, "_authenticated", True)
    )
    monkeypatch.setattr(DocAIClient, "get_json", get_json)
    monkeypatch.setattr(DocAIClient, "list_all", list_all)
    monkeypatch.setattr(DocAIClient, "post_json", post_json)
    monkeypatch.setattr(DocAIClient, "upload", upload)
    monkeypatch.setattr(DocAIClient, "download", download)

    runner = CliRunner()
    commands = [
        ["health"],
        ["auth", "status"],
        ["--json", "projects", "list"],
        ["datasets", "list", "--project", "project-1"],
        [
            "workflows",
            "list",
            "--project",
            "project-1",
            "--type",
            "extract_structured",
            "--status",
            "approved",
        ],
        ["workflows", "contract", "workflow-1"],
        ["documents", "list", "--dataset", "dataset-1"],
        ["documents", "upload", "--dataset", "dataset-1", str(tmp_path / "upload.pdf")],
        [
            "runs",
            "submit",
            "--workflow",
            "workflow-1",
            "--dataset",
            "dataset-1",
            "--document-id",
            "document-1",
            "--client-reference",
            "caller-1",
        ],
        ["runs", "list", "--project", "p", "--dataset", "d", "--status", "running"],
        ["runs", "show", "run-1"],
        ["runs", "progress", "run-1"],
        ["runs", "wait", "run-1", "--timeout", "1"],
        ["runs", "cancel", "run-1"],
        ["runs", "retry", "run-1"],
        ["runs", "export", "run-1", "--output", str(tmp_path / "result.json")],
        ["review", "list", "--run", "run-1"],
    ]
    (tmp_path / "upload.pdf").write_bytes(b"pdf")
    for args in commands:
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (args, result.output, result.exception)


def test_human_cli_error_is_written_to_stderr_and_keeps_trace(monkeypatch):
    from docai_cli.client import DocAIClient

    def get_json(self, path, **kwargs):
        del self, path, kwargs
        raise CliError("resource missing", EXIT_NOT_FOUND, "NOT_FOUND", trace_id="trace-abc")

    monkeypatch.setattr(DocAIClient, "get_json", get_json)
    result = CliRunner().invoke(app, ["runs", "show", "missing"])
    assert result.exit_code == EXIT_NOT_FOUND
    assert "NOT_FOUND" in result.output
    assert "trace-abc" in result.output


def test_json_cli_error_has_data_trace_and_retry_metadata(monkeypatch):
    from docai_cli.client import DocAIClient

    def post_json(self, path, payload, *, headers=None):
        del self, path, payload, headers
        raise CliError(
            "try later",
            3,
            "INVOCATION_IN_PROGRESS",
            trace_id="trace-2",
            operation={"retry_after": "2"},
            retryable=True,
        )

    monkeypatch.setattr(DocAIClient, "post_json", post_json)
    result = CliRunner().invoke(
        app,
        ["--json", "runs", "submit", "--workflow", "w", "--dataset", "d", "--document-id", "doc"],
    )
    assert result.exit_code == EXIT_VALIDATION
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "INVOCATION_IN_PROGRESS"
    assert payload["trace_id"] == "trace-2"
    assert payload["operation"]["retry_after"] == "2"
    assert payload["retryable"] is True


def test_api_error_reads_top_level_drf_error_fields(monkeypatch):
    payload = {
        "success": False,
        "error_code": "INVALID_INPUT",
        "message": "bad",
        "details": {"field": "x"},
        "trace_id": "trace-top",
        "retryable": False,
    }
    client, _ = client_with(
        monkeypatch,
        [FakeResponse(status=422, data=payload)],
        username="u",
        password="p",
        auth_mode="basic",
    )
    client._authenticated = True
    with pytest.raises(CliError) as captured:
        client.get_json("projects/")
    assert captured.value.error_code == "INVALID_INPUT"
    assert captured.value.details == {"field": "x"}
    assert captured.value.retryable is False


def test_auth_rejects_unknown_mode_and_missing_csrf_cookie(monkeypatch):
    client, _ = client_with(monkeypatch, username="operator", password="secret", auth_mode="token")
    with pytest.raises(CliError, match="session.*basic"):
        client.authenticate()

    client, session = client_with(
        monkeypatch,
        [FakeResponse(data=envelope({"user": None}))],
        username="operator",
        password="secret",
    )
    session.cookies.clear()
    with pytest.raises(CliError, match="CSRF cookie"):
        client.authenticate()


@pytest.mark.parametrize(
    ("exception", "exit_code"),
    [
        (requests.Timeout(), EXIT_TIMEOUT),
        (requests.ConnectionError(), EXIT_TRANSPORT),
    ],
)
def test_transport_failures_have_distinct_exit_codes(monkeypatch, exception, exit_code):
    client, session = client_with(
        monkeypatch, username="operator", password="secret", auth_mode="basic"
    )
    client._authenticated = True

    def fail(*args, **kwargs):
        del args, kwargs
        raise exception

    session.request = fail
    with pytest.raises(CliError) as captured:
        client.get_json("projects/")
    assert captured.value.exit_code == exit_code


def test_timeout_deadline_is_applied_before_network_request(monkeypatch):
    client, _ = client_with(monkeypatch, username="u", password="p", auth_mode="basic")
    client.deadline = 10
    monkeypatch.setattr("docai_cli.client.time.monotonic", lambda: 11)
    with pytest.raises(CliError) as captured:
        client._request_timeout()
    assert captured.value.error_code == "OPERATION_TIMEOUT"


def test_upload_success_streams_multipart_and_closes_source_file(monkeypatch, tmp_path):
    client, session = client_with(
        monkeypatch,
        [FakeResponse(data=envelope({"accepted": []}))],
        username="u",
        password="p",
        auth_mode="basic",
    )
    client._authenticated = True
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"source bytes")
    data, _ = client.upload("dataset-1", [source])
    assert data == {"accepted": []}
    assert session.calls[0][0] == "POST"
    assert "multipart/form-data" in session.calls[0][2]["headers"]["Content-Type"]
    assert session.calls[0][2]["data"].len > source.stat().st_size


def test_upload_reports_streamed_bytes_without_changing_request_body(monkeypatch, tmp_path):
    client, session = client_with(
        monkeypatch,
        [FakeResponse(data=envelope({"accepted": [], "rejected": []}))],
        username="u",
        password="p",
        auth_mode="basic",
    )
    client._authenticated = True
    source = tmp_path / "large.pdf"
    source.write_bytes(b"document" * 4096)
    updates: list[tuple[int, int]] = []
    original_request = session.request

    def consume_request(method, url, **kwargs):
        body = kwargs["data"]
        while body.read(4096):
            pass
        return original_request(method, url, **kwargs)

    session.request = consume_request
    client.upload(
        "dataset-1", [source], on_progress=lambda sent, total: updates.append((sent, total))
    )

    assert updates[0][0] == 0
    assert updates[-1] == (updates[0][1], updates[0][1])
    assert updates[-1][0] > source.stat().st_size
    assert session.calls[0][2]["headers"]["Content-Type"].startswith("multipart/form-data")


def test_pagination_stops_at_cap_and_returns_partial_records(monkeypatch):
    client, _ = client_with(monkeypatch, username="u", password="p", auth_mode="basic")
    client._authenticated = True
    index = 0

    def next_page(path, **kwargs):
        nonlocal index
        del path, kwargs
        index += 1
        return {
            "results": [{"id": str(index)}],
            "next": f"https://docai.example/api/v1/projects/?page={index + 1}",
        }, FakeResponse()

    client.get_json = next_page  # type: ignore[method-assign]
    with pytest.raises(CliError) as captured:
        client.list_all("projects/", all_pages=True)
    assert captured.value.error_code == "PAGE_LIMIT_REACHED"
    assert len(captured.value.data) == 1000


def test_export_can_replace_existing_file_only_when_forced(monkeypatch, tmp_path):
    client, _ = client_with(
        monkeypatch,
        [FakeResponse(body=b"new bytes")],
        username="u",
        password="p",
        auth_mode="basic",
    )
    client._authenticated = True
    output = tmp_path / "result.json"
    output.write_bytes(b"old bytes")
    client.download("runs/run/export/json/", output, force=True)
    assert output.read_bytes() == b"new bytes"


@pytest.mark.parametrize(
    ("headers", "expected_total"),
    [({"Content-Length": "9"}, 9), ({"Content-Length": "4", "Content-Encoding": "gzip"}, None)],
)
def test_export_progress_uses_known_length_only_for_identity_content(
    monkeypatch, tmp_path, headers, expected_total
):
    client, _ = client_with(
        monkeypatch,
        [FakeResponse(body=b"new bytes", headers=headers)],
        username="u",
        password="p",
        auth_mode="basic",
    )
    client._authenticated = True
    updates: list[tuple[int, int | None]] = []
    output = tmp_path / "result.json"
    client.download(
        "runs/run/export/json/",
        output,
        on_progress=lambda received, total: updates.append((received, total)),
    )
    assert output.read_bytes() == b"new bytes"
    assert updates == [(0, expected_total), (9, expected_total)]


def test_export_requires_existing_parent_and_maps_server_errors(monkeypatch, tmp_path):
    client, _ = client_with(monkeypatch, username="u", password="p", auth_mode="basic")
    with pytest.raises(CliError, match="directory does not exist"):
        client.download("runs/run/export/json/", tmp_path / "missing" / "result.json")

    client, _ = client_with(
        monkeypatch,
        [FakeResponse(status=503, data={"html": "error"})],
        username="u",
        password="p",
        auth_mode="basic",
    )
    client._authenticated = True
    with pytest.raises(CliError) as captured:
        client.download("runs/run/export/json/", tmp_path / "result.json")
    assert captured.value.exit_code == 6
    assert captured.value.error_code == "HTTP_503"


def test_export_maps_temporary_file_creation_failure(monkeypatch, tmp_path):
    client, session = client_with(
        monkeypatch,
        [FakeResponse(body=b"complete export")],
        username="u",
        password="p",
        auth_mode="basic",
    )
    client._authenticated = True

    def fail_mkstemp(*args, **kwargs):
        del args, kwargs
        raise OSError("quota exceeded")

    monkeypatch.setattr("docai_cli.client.tempfile.mkstemp", fail_mkstemp)
    with pytest.raises(CliError) as captured:
        client.download("runs/run/export/json/", tmp_path / "result.json")

    assert captured.value.error_code == "EXPORT_WRITE_FAILED"
    assert session.responses == []


def test_non_json_server_error_is_not_rendered_as_response_body(monkeypatch):
    client, _ = client_with(
        monkeypatch, [FakeResponse(status=502)], username="u", password="p", auth_mode="basic"
    )
    client._authenticated = True
    with pytest.raises(CliError) as captured:
        client.get_json("projects/")
    assert "non-JSON" in captured.value.message


def test_human_error_can_show_trace_operation_and_safe_details(capsys):
    emit_human_error(
        CliError(
            "bad request",
            EXIT_VALIDATION,
            "INVALID_INPUT",
            trace_id="trace-1",
            details={"field": "name"},
            operation={"run_id": "run-1"},
        ),
        debug=True,
    )
    out, err = capsys.readouterr()
    assert out == ""
    assert "trace-1" in err
    assert "run_id=run-1" in err
    assert '"field": "name"' in err


def test_color_environment_controls_and_human_empty_output(capsys, monkeypatch):
    from docai_cli.output import color_disabled

    monkeypatch.setenv("NO_COLOR", "1")
    assert color_disabled()
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert not color_disabled()
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    emit_rows([], json_mode=False)
    out, _ = capsys.readouterr()
    assert out == "No results.\n"


def test_table_renders_only_for_a_wide_terminal(monkeypatch):
    from docai_cli import output

    capture = io.StringIO()
    capture.isatty = lambda: True  # type: ignore[attr-defined]
    monkeypatch.setattr(output.sys, "stdout", capture)
    monkeypatch.setattr(output, "shutil_terminal_width", lambda: 200)
    output.emit_rows(
        [{"name": "Sample", "id": "full-uuid"}], json_mode=False, columns=("name", "id")
    )
    assert "Sample" in capture.getvalue()
    assert "full-uuid" in capture.getvalue()


@pytest.mark.parametrize("width", [120, 70, 45])
def test_project_table_keeps_full_id_as_columns_adapt(monkeypatch, width):
    from docai_cli import output

    capture = io.StringIO()
    capture.isatty = lambda: True  # type: ignore[attr-defined]
    monkeypatch.setattr(output.sys, "stdout", capture)
    monkeypatch.setattr(output, "shutil_terminal_width", lambda: width)
    identifier = "ef7ea548-a18a-4bcb-9c2b-7df9d675f472"
    output.emit_rows(
        [
            {
                "name": "Sample banking documents",
                "slug": "sample-banking-docs",
                "modified": "2026-09-25T12:00:36Z",
                "id": identifier,
            }
        ],
        json_mode=False,
        kind="projects",
        no_color=True,
        utc=True,
    )
    human = capture.getvalue()
    assert identifier in human
    assert "…" not in human
    assert "\x1b" not in human
    if width == 120:
        assert "sample-banking-docs" in human
        assert "2026-09-25 12:00" in human
    elif width == 70:
        assert "\t" not in human
        assert "sample-banking-docs" not in human
    else:
        assert "\t" in human


def test_no_color_applies_to_human_errors_even_when_color_is_forced(monkeypatch):
    from docai_cli import output

    capture = io.StringIO()
    capture.isatty = lambda: True  # type: ignore[attr-defined]
    monkeypatch.setattr(output.sys, "stderr", capture)
    monkeypatch.setenv("FORCE_COLOR", "1")
    output.emit_human_error(
        CliError("Could not load the run.", EXIT_NOT_FOUND, "NOT_FOUND"), no_color=True
    )
    assert "error: Could not load the run." in capture.getvalue()
    assert "\x1b" not in capture.getvalue()


def test_main_moves_json_flag_and_reports_startup_failures(monkeypatch, capsys):
    from docai_cli import main as main_module

    invoked: dict[str, Any] = {}
    monkeypatch.setattr(sys, "argv", ["docai", "projects", "list", "--json"])
    monkeypatch.setattr(main_module, "app", lambda **kwargs: invoked.update(kwargs))
    main_module.main()
    assert invoked["args"] == ["--json", "projects", "list"]

    def fail_app(**kwargs):
        del kwargs
        raise CliError("startup failed", EXIT_VALIDATION, "BAD_OPTION")

    monkeypatch.setattr(main_module, "app", fail_app)
    monkeypatch.setattr(sys, "argv", ["docai", "--json", "health"])
    with pytest.raises(SystemExit) as captured:
        main_module.main()
    out, err = capsys.readouterr()
    assert captured.value.code == EXIT_VALIDATION
    assert err == ""
    assert json.loads(out)["error"]["code"] == "BAD_OPTION"


def test_main_keyboard_interrupt_is_machine_readable(monkeypatch, capsys):
    from docai_cli import main as main_module

    monkeypatch.setattr(sys, "argv", ["docai", "--json", "health"])
    monkeypatch.setattr(
        main_module, "app", lambda **kwargs: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    with pytest.raises(SystemExit) as captured:
        main_module.main()
    out, err = capsys.readouterr()
    assert captured.value.code == 130
    assert err == ""
    assert json.loads(out)["error"]["code"] == "INTERRUPTED"


def test_wait_honors_etag_and_retry_after_without_poll_progress_on_stdout(monkeypatch):
    from docai_cli.client import DocAIClient

    observed: list[dict[str, str] | None] = []
    responses = iter(
        [
            (
                {"run_id": "run-1", "completed": False},
                FakeResponse(202, headers={"ETag": 'W/"one"', "Retry-After": "1"}),
            ),
            (None, FakeResponse(304, headers={"ETag": 'W/"one"', "Retry-After": "1"})),
            ({"run_id": "run-1", "completed": True, "status": "succeeded"}, FakeResponse(200)),
        ]
    )

    def get_json(self, path, *, api=True, headers=None):
        del self, path, api
        observed.append(headers)
        return next(responses)

    monkeypatch.setattr(DocAIClient, "get_json", get_json)
    monkeypatch.setattr("docai_cli.commands.time.sleep", lambda _delay: None)
    result = CliRunner().invoke(app, ["--json", "runs", "wait", "run-1", "--timeout", "10"])
    assert result.exit_code == 0, result.output
    assert observed == [None, {"If-None-Match": 'W/"one"'}, {"If-None-Match": 'W/"one"'}]
    assert json.loads(result.output)["data"]["status"] == "succeeded"
    assert "still processing" not in result.output


def test_human_wait_reports_changed_state_then_a_compact_failure_summary(monkeypatch):
    pending = {
        "run_id": "run-1",
        "status": "running",
        "stage": "processing",
        "completed": False,
        "counts": {"run_items": {"total": 3, "succeeded": 1, "failed": 0, "skipped": 0}},
    }
    complete = {
        **pending,
        "status": "partial",
        "completed": True,
        "counts": {"run_items": {"total": 3, "succeeded": 2, "failed": 1, "skipped": 0}},
        "review": {"total": 0, "fields": 0},
    }
    responses = iter(
        [
            (pending, FakeResponse(202, headers={"ETag": 'W/"one"'})),
            (None, FakeResponse(304, headers={"ETag": 'W/"one"'})),
            (complete, FakeResponse(200)),
        ]
    )

    def get_json(self, path, *, api=True, headers=None):
        del self, path, api, headers
        return next(responses)

    monkeypatch.setattr(DocAIClient, "get_json", get_json)
    monkeypatch.setattr("docai_cli.commands.time.sleep", lambda _delay: None)
    result = CliRunner().invoke(app, ["runs", "wait", "run-1", "--timeout", "10"])

    assert result.exit_code == 0, result.output
    assert result.stderr.count("1/3 items") == 1
    assert "Run partial: run-1" in result.stdout
    assert "2 succeeded · 1 failed / 3 total" in result.stdout
    assert "docai runs progress run-1" in result.stdout
    assert "'run_items':" not in result.stdout


def test_run_completion_guides_field_review_before_export(capsys):
    data = {
        "run_id": "full-run-id",
        "status": "succeeded",
        "counts": {"run_items": {"total": 1, "succeeded": 1, "failed": 0, "skipped": 0}},
        "review": {"total": 2, "fields": 2},
    }
    emit_run_completion(data, json_mode=False)
    human, err = capsys.readouterr()
    assert err == ""
    assert "1 succeeded / 1 total" in human
    assert "2 need attention" in human
    assert "docai review list --run full-run-id" in human
    assert "runs export" not in human

    emit_run_completion(data, json_mode=True)
    agent, err = capsys.readouterr()
    assert err == ""
    assert agent.count("\n") == 1
    assert json.loads(agent)["data"] == data


def test_progress_animation_requires_both_terminal_streams_and_json_stays_quiet(
    monkeypatch, capsys
):
    from docai_cli.output import run_status, transfer_status

    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    with transfer_status("Sending 1 file", json_mode=False) as report:
        assert report is None
    with run_status("run-1", json_mode=True) as report:
        report({"status": "running"})
    assert capsys.readouterr() == ("", "")


def test_wait_timeout_returns_run_handle(monkeypatch):
    from docai_cli.client import DocAIClient

    def pending(self, path, *, api=True, headers=None):
        del self, path, api, headers
        return {"run_id": "run-1", "completed": False}, FakeResponse(
            202, headers={"Retry-After": "2"}
        )

    clock = iter([0.0, 0.5, 2.0])
    monkeypatch.setattr(DocAIClient, "get_json", pending)
    monkeypatch.setattr("docai_cli.commands.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("docai_cli.commands.time.sleep", lambda _delay: None)
    result = CliRunner().invoke(app, ["--json", "runs", "wait", "run-1", "--timeout", "1"])
    assert result.exit_code == EXIT_TIMEOUT
    payload = json.loads(result.output)
    assert payload["operation"] == {"run_id": "run-1"}
    assert payload["data"]["run_id"] == "run-1"


def test_session_wait_timeout_emits_one_json_envelope_with_run_handle(monkeypatch, capsys):
    from docai_cli import main as main_module

    client, session = client_with(
        monkeypatch,
        [
            FakeResponse(
                202,
                data=envelope({"run_id": "run-1", "completed": False, "status": "processing"}),
                headers={"ETag": 'W/"pending"', "Retry-After": "0.25"},
            )
        ],
        username="operator",
        password="secret",
    )
    client._authenticated = True
    monkeypatch.setattr(main_module, "DocAIClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(sys, "argv", ["docai", "--json", "runs", "wait", "run-1", "--timeout", "1"])
    clock = iter((0.0, 0.0, 2.0))
    monkeypatch.setattr(time, "monotonic", lambda: next(clock, 2.0))
    monkeypatch.setattr("docai_cli.commands.time.sleep", lambda _delay: None)

    with pytest.raises(SystemExit) as captured:
        main_module.main()

    out, err = capsys.readouterr()
    assert captured.value.code == EXIT_TIMEOUT
    assert err == ""
    assert out.count("\n") == 1
    payload = json.loads(out)
    assert payload["error"]["code"] == "POLL_TIMEOUT"
    assert payload["operation"] == {"run_id": "run-1"}
    assert payload["data"] == {"run_id": "run-1", "completed": False, "status": "processing"}
    assert session.calls[-1][0] == "POST"  # Authenticated logout ran as bounded cleanup.


def test_request_timeout_and_network_errors_are_redacted(monkeypatch):
    client, session = client_with(
        monkeypatch, username="operator", password="secret", auth_mode="basic"
    )
    client._authenticated = True

    def fail(*args, **kwargs):
        del args, kwargs
        raise requests.ConnectionError("sensitive URL and credential data")

    session.request = fail
    with pytest.raises(CliError) as captured:
        client.get_json("projects/")
    assert captured.value.error_code == "NETWORK_ERROR"
    assert "credential" not in captured.value.message
