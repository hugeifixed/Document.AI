"""Contract tests for the repository's network-free integration client helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "workflow_tester.py"
SPEC = importlib.util.spec_from_file_location("docai_workflow_tester", EXAMPLE)
assert SPEC and SPEC.loader
client = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = client
SPEC.loader.exec_module(client)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"unexpected HTTP {self.status_code}")


class FakeSession:
    def __init__(
        self,
        *,
        gets: list[FakeResponse] | None = None,
        posts: list[FakeResponse] | None = None,
    ) -> None:
        self.cookies = {"csrftoken": "csrf"}
        self.gets = list(gets or [])
        self.posts = list(posts or [])
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.get_calls.append((url, kwargs))
        return self.gets.pop(0)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append((url, kwargs))
        return self.posts.pop(0)


def settings(tmp_path: Path, **changes: Any):
    values = {
        "base_url": "https://docai.example",
        "username": "integration-user",
        "workflow": "workflow-id",
        "dataset": "dataset-id",
        "output": tmp_path / "result.json",
        "timeout_seconds": 30,
        "idempotency_key": "upstream-request-1",
    }
    values.update(changes)
    return client.Settings(**values)


def envelope(data: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "data": data, "trace_id": "trace"}


def test_workflow_contract_is_preflighted_before_upload(tmp_path):
    session = FakeSession(
        gets=[
            FakeResponse(
                200,
                envelope(
                    {
                        "id": "workflow-id",
                        "name": "W-2 extraction",
                        "version": 3,
                        "workflow_type": "extract_structured",
                    }
                ),
            )
        ]
    )

    contract = client.fetch_workflow_contract(settings(tmp_path), session)

    assert contract["id"] == "workflow-id"
    assert session.get_calls[0][0].endswith("/workflows/workflow-id/contract/")


def test_document_first_upload_accepts_reused_document(tmp_path):
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"pdf")
    response = FakeResponse(
        200,
        envelope(
            {
                "accepted": [{"id": "document-id", "original_filename": source.name}],
                "reused_document_ids": ["document-id"],
                "rejected": [],
            }
        ),
    )
    session = FakeSession(posts=[response])

    document_ids = client.upload_documents(
        settings(tmp_path, files=[source]),
        session,
    )

    assert document_ids == ["document-id"]
    assert session.post_calls[0][0].endswith("/datasets/dataset-id/upload/")
    assert session.post_calls[0][1]["headers"]["X-CSRFToken"] == "csrf"


def test_poll_reuses_etag_across_304_until_terminal(tmp_path, monkeypatch):
    results_url = "https://docai.example/api/v1/runs/run-id/results/"
    pending = envelope({"run_id": "run-id", "completed": False})
    terminal = envelope({"run_id": "run-id", "completed": True, "status": "succeeded"})
    session = FakeSession(
        gets=[
            FakeResponse(202, pending, {"ETag": '"v1"', "Retry-After": "1"}),
            FakeResponse(304, headers={"ETag": '"v1"', "Retry-After": "1"}),
            FakeResponse(200, terminal, {"ETag": '"v2"'}),
        ]
    )
    monkeypatch.setattr(client.time, "sleep", lambda _delay: None)
    accepted = FakeResponse(
        202,
        envelope({"run_id": "run-id", "links": {"results": results_url}}),
        {"Retry-After": "1"},
    )

    result = client.wait_for_result(settings(tmp_path), session, accepted)

    assert result == terminal
    assert session.get_calls[0][1]["headers"] is None
    assert session.get_calls[1][1]["headers"] == {"If-None-Match": '"v1"'}
    assert session.get_calls[2][1]["headers"] == {"If-None-Match": '"v1"'}


def test_paginated_collection_follows_next_link_and_stays_on_origin(tmp_path):
    first = "https://docai.example/api/v1/fields/?run=run-id"
    second = "https://docai.example/api/v1/fields/?run=run-id&page=2"
    session = FakeSession(
        gets=[
            FakeResponse(200, envelope({"results": [{"id": "one"}], "next": second})),
            FakeResponse(200, envelope({"results": [{"id": "two"}], "next": None})),
        ]
    )

    results = client.fetch_paginated_collection(settings(tmp_path), session, first)

    assert results == [{"id": "one"}, {"id": "two"}]
    assert [url for url, _ in session.get_calls] == [first, second]

    with pytest.raises(SystemExit, match="different host"):
        client.fetch_paginated_collection(
            settings(tmp_path),
            FakeSession(),
            "https://attacker.example/api/v1/fields/",
        )
