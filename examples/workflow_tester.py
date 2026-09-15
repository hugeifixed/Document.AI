"""Small local tester for the workflow invocation API.

Examples:
    python examples/workflow_tester.py --config examples/workflow_tester.config.json
    python examples/workflow_tester.py --workflow UUID --dataset UUID --username admin sample.pdf
    python examples/workflow_tester.py --workflow UUID --dataset UUID --username admin --document-id DOC_UUID
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from getpass import getpass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import requests

API_PREFIX = "/api/v1"


@dataclass
class Settings:
    base_url: str = "http://localhost:8000"
    username: str = ""
    password: str = ""
    workflow: str = ""
    dataset: str = ""
    name: str = "Local workflow API test"
    files: list[Path] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    output: Path = Path("workflow-result.json")
    timeout_seconds: int = 600
    idempotency_key: str = ""
    dry_run: bool = False


def read_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def build_settings(args: argparse.Namespace) -> Settings:
    config = read_config(args.config)
    files = args.files or list_value(config.get("files"))
    document_ids = args.document_ids or list_value(config.get("document_ids"))
    output = args.output or config.get("output") or "workflow-result.json"

    settings = Settings(
        base_url=(args.base_url or config.get("base_url") or "http://localhost:8000").rstrip("/"),
        username=args.username or config.get("username") or "",
        password=args.password or config.get("password") or "",
        workflow=args.workflow or config.get("workflow") or "",
        dataset=args.dataset or config.get("dataset") or "",
        name=args.name or config.get("name") or "Local workflow API test",
        files=[Path(path) for path in files],
        document_ids=document_ids,
        output=Path(output),
        timeout_seconds=int(args.timeout_seconds or config.get("timeout_seconds") or 600),
        idempotency_key=(args.idempotency_key or config.get("idempotency_key") or str(uuid4())),
        dry_run=bool(args.dry_run or config.get("dry_run") or False),
    )
    validate_settings(settings)
    return settings


def validate_settings(settings: Settings) -> None:
    missing = [name for name in ("username", "workflow", "dataset") if not getattr(settings, name)]
    if missing:
        raise SystemExit(f"Missing required setting(s): {', '.join(missing)}")
    if bool(settings.files) == bool(settings.document_ids):
        raise SystemExit("Provide either files or document_ids, but not both.")
    for path in settings.files:
        if not path.is_file():
            raise SystemExit(f"Input file was not found: {path}")


def same_origin(base_url: str, url: str) -> bool:
    base = urlsplit(base_url)
    candidate = urlsplit(url)
    return (base.scheme, base.netloc) == (candidate.scheme, candidate.netloc)


def csrf_token(session: requests.Session, base_url: str) -> str:
    cookie = session.cookies.get("csrftoken")
    if not cookie:
        raise SystemExit(f"CSRF cookie was not set by {base_url}{API_PREFIX}/auth/session/")
    return cookie


def sign_in(settings: Settings) -> requests.Session:
    session = requests.Session()
    session.get(f"{settings.base_url}{API_PREFIX}/auth/session/", timeout=30).raise_for_status()
    password = settings.password or getpass("Password: ")
    response = session.post(
        f"{settings.base_url}{API_PREFIX}/auth/login/",
        json={"username": settings.username, "password": password},
        headers={
            "X-CSRFToken": csrf_token(session, settings.base_url),
            "Origin": settings.base_url,
            "Referer": f"{settings.base_url}/",
        },
        timeout=30,
    )
    response.raise_for_status()
    return session


def invoke_workflow(settings: Settings, session: requests.Session) -> requests.Response:
    url = f"{settings.base_url}{API_PREFIX}/workflows/{settings.workflow}/invoke/"
    headers = {
        "X-CSRFToken": csrf_token(session, settings.base_url),
        "Origin": settings.base_url,
        "Referer": f"{settings.base_url}/",
        "Idempotency-Key": settings.idempotency_key,
    }
    if settings.document_ids:
        return session.post(
            url,
            json={
                "dataset": settings.dataset,
                "document_ids": settings.document_ids,
                "name": settings.name,
            },
            headers=headers,
            timeout=settings.timeout_seconds,
        )
    with ExitStack() as stack:
        upload_files = [
            ("files", (path.name, stack.enter_context(path.open("rb")))) for path in settings.files
        ]
        return session.post(
            url,
            data={"dataset": settings.dataset, "name": settings.name},
            files=upload_files,
            headers=headers,
            timeout=settings.timeout_seconds,
        )


def save_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def wait_for_result(
    settings: Settings,
    session: requests.Session,
    response: requests.Response,
) -> dict[str, Any]:
    deadline = time.monotonic() + settings.timeout_seconds
    while True:
        payload = response.json()
        if response.status_code not in (200, 202):
            save_payload(settings.output, payload)
            response.raise_for_status()
        data = payload["data"]
        if data["completed"]:
            return payload
        if time.monotonic() >= deadline:
            save_payload(settings.output, payload)
            raise SystemExit(
                "Timed out waiting for completion. "
                f"The latest response was saved to {settings.output}."
            )
        results_url = data["results_url"]
        if not same_origin(settings.base_url, results_url):
            raise SystemExit(f"Refusing to poll a different host: {results_url}")
        delay = int(response.headers.get("Retry-After", "2"))
        print(f"Run {data['run_id']} is {data['status']}; polling again in {delay}s...")
        time.sleep(delay)
        response = session.get(results_url, timeout=30)


def print_summary(payload: dict[str, Any], output: Path) -> None:
    data = payload["data"]
    results = data.get("results") or {}
    print()
    print(f"Run ID: {data['run_id']}")
    print(f"Status: {data['status']}")
    print(f"Workflow: {data['workflow']['name']} v{data['workflow']['version']}")
    print(f"Fields: {len(results.get('fields') or [])}")
    print(f"Classifications: {len(results.get('classifications') or [])}")
    print(f"Segments: {len(results.get('segments') or [])}")
    print(f"Errors: {len(data.get('errors') or []) + len(results.get('errors') or [])}")
    print(f"Saved JSON: {output}")


def print_dry_run(settings: Settings) -> None:
    body: dict[str, Any] = {
        "dataset": settings.dataset,
        "name": settings.name,
    }
    mode = "json"
    if settings.document_ids:
        body["document_ids"] = settings.document_ids
    else:
        mode = "multipart"
        body["files"] = [str(path) for path in settings.files]
    print("Dry run only. No login, upload, or workflow run was created.")
    print(f"POST {settings.base_url}{API_PREFIX}/workflows/{settings.workflow}/invoke/")
    print(f"Mode: {mode}")
    print(f"Idempotency-Key: {settings.idempotency_key}")
    print(json.dumps(body, indent=2))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="Files to upload and process.")
    parser.add_argument("--config", type=Path, help="JSON config file.")
    parser.add_argument("--base-url")
    parser.add_argument("--username")
    parser.add_argument("--password", help="Optional. If omitted, you will be prompted.")
    parser.add_argument("--workflow", help="Pinned workflow version UUID.")
    parser.add_argument("--dataset", help="Dataset UUID in the workflow project.")
    parser.add_argument("--name", help="Optional run name.")
    parser.add_argument("--document-id", action="append", dest="document_ids")
    parser.add_argument("--output")
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument(
        "--idempotency-key",
        help="Reuse this value only when retrying the same logical invocation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the request that would be made without signing in or running it.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    settings = build_settings(parse_args(argv or sys.argv[1:]))
    if settings.dry_run:
        print_dry_run(settings)
        return 0
    session = sign_in(settings)
    print(f"Idempotency-Key: {settings.idempotency_key}")
    response = invoke_workflow(settings, session)
    payload = wait_for_result(settings, session, response)
    save_payload(settings.output, payload)
    print_summary(payload, settings.output)
    return 0 if payload["data"]["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
