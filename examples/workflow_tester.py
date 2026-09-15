"""Small client for the approved-workflow integration API.

The normal flow uploads documents to a dataset, invokes the workflow with the
returned document IDs, polls the bounded result manifest, and follows its
paginated collection links. ``--multipart-invoke`` retains the compact upload
and invoke request for clients that cannot use the document-first flow.

Examples:
    python examples/workflow_tester.py --config examples/workflow_tester.config.json
    python examples/workflow_tester.py --workflow UUID --dataset UUID --username admin sample.pdf
    python examples/workflow_tester.py --workflow UUID --dataset UUID --username admin --document-id DOC_UUID
    python examples/workflow_tester.py --resume-replay --workflow UUID --dataset UUID \
      --username admin --document-id DOC_UUID --idempotency-key ORIGINAL_KEY \
      --name ORIGINAL_NAME --client-reference ORIGINAL_REFERENCE
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
PAGINATED_RESOURCES = ("run_items", "fields", "classifications", "segments")


@dataclass
class Settings:
    base_url: str = "http://localhost:8000"
    username: str = ""
    password: str = ""
    workflow: str = ""
    dataset: str = ""
    name: str = "Local workflow API test"
    client_reference: str = ""
    files: list[Path] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    output: Path = Path("workflow-result.json")
    timeout_seconds: int = 600
    idempotency_key: str = ""
    multipart_invoke: bool = False
    resume_replay: bool = False
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
    resume_replay = bool(args.resume_replay or config.get("resume_replay") or False)
    supplied_idempotency_key = args.idempotency_key or config.get("idempotency_key") or ""
    configured_name = config.get("name")
    supplied_name = args.name is not None or isinstance(configured_name, str)
    name = args.name if args.name is not None else configured_name if supplied_name else None
    configured_reference = config.get("client_reference")
    supplied_reference = args.client_reference is not None or isinstance(configured_reference, str)
    client_reference = (
        args.client_reference
        if args.client_reference is not None
        else configured_reference
        if supplied_reference
        else ""
    )
    if resume_replay:
        explicit_inputs = {
            "idempotency_key": bool(supplied_idempotency_key),
            "name": supplied_name,
            "client_reference": supplied_reference,
        }
        missing = [name for name, supplied in explicit_inputs.items() if not supplied]
        if missing:
            raise SystemExit(
                "--resume-replay requires the original caller-supplied value(s): "
                + ", ".join(missing)
                + "."
            )

    settings = Settings(
        base_url=(args.base_url or config.get("base_url") or "http://localhost:8000").rstrip("/"),
        username=args.username or config.get("username") or "",
        password=args.password or config.get("password") or "",
        workflow=args.workflow or config.get("workflow") or "",
        dataset=args.dataset or config.get("dataset") or "",
        name=name if isinstance(name, str) else "Local workflow API test",
        client_reference=client_reference,
        files=[Path(path) for path in files],
        document_ids=document_ids,
        output=Path(output),
        timeout_seconds=int(args.timeout_seconds or config.get("timeout_seconds") or 600),
        idempotency_key=supplied_idempotency_key or str(uuid4()),
        multipart_invoke=bool(args.multipart_invoke or config.get("multipart_invoke") or False),
        resume_replay=resume_replay,
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
    if settings.multipart_invoke and not settings.files:
        raise SystemExit("--multipart-invoke requires one or more files.")
    if settings.resume_replay and (
        settings.files or settings.multipart_invoke or not settings.document_ids
    ):
        raise SystemExit(
            "--resume-replay requires original --document-id values and cannot upload files."
        )
    for path in settings.files:
        if not path.is_file():
            raise SystemExit(f"Input file was not found: {path}")


def same_origin(base_url: str, url: str) -> bool:
    base = urlsplit(base_url)
    candidate = urlsplit(url)
    return (base.scheme, base.netloc) == (candidate.scheme, candidate.netloc)


def require_same_origin(base_url: str, url: str) -> None:
    if not same_origin(base_url, url):
        raise SystemExit(f"Refusing to follow a URL on a different host: {url}")


def retry_after_seconds(response: requests.Response, default: float = 2.0) -> float:
    try:
        delay = float(response.headers.get("Retry-After", default))
    except (TypeError, ValueError):
        delay = default
    return min(max(delay, 0.1), 60.0)


def csrf_token(session: requests.Session, base_url: str) -> str:
    cookie = session.cookies.get("csrftoken")
    if not cookie:
        raise SystemExit(f"CSRF cookie was not set by {base_url}{API_PREFIX}/auth/session/")
    return cookie


def mutation_headers(session: requests.Session, base_url: str) -> dict[str, str]:
    return {
        "X-CSRFToken": csrf_token(session, base_url),
        "Origin": base_url,
        "Referer": f"{base_url}/",
    }


def sign_in(settings: Settings) -> requests.Session:
    session = requests.Session()
    session.get(f"{settings.base_url}{API_PREFIX}/auth/session/", timeout=30).raise_for_status()
    password = settings.password or getpass("Password: ")
    response = session.post(
        f"{settings.base_url}{API_PREFIX}/auth/login/",
        json={"username": settings.username, "password": password},
        headers=mutation_headers(session, settings.base_url),
        timeout=30,
    )
    response.raise_for_status()
    return session


def response_payload(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except requests.JSONDecodeError as exc:
        raise SystemExit(f"Server returned non-JSON HTTP {response.status_code}.") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Server returned an unexpected HTTP {response.status_code} response.")
    return payload


def fetch_workflow_contract(settings: Settings, session: requests.Session) -> dict[str, Any]:
    """Fail before upload when the pinned workflow is unavailable or unapproved."""
    url = f"{settings.base_url}{API_PREFIX}/workflows/{settings.workflow}/contract/"
    response = session.get(url, timeout=30)
    payload = response_payload(response)
    if response.status_code != 200:
        save_payload(settings.output, {"stage": "workflow_contract", "response": payload})
        response.raise_for_status()
    contract = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not contract.get("id"):
        raise SystemExit("Workflow contract response did not contain a workflow ID.")
    print(
        f"Workflow: {contract.get('name', contract['id'])} v{contract.get('version', '?')} "
        f"({contract.get('workflow_type', 'unknown type')})"
    )
    return contract


def upload_documents(settings: Settings, session: requests.Session) -> list[str]:
    """Store documents first so retries can refer to stable document IDs."""
    url = f"{settings.base_url}{API_PREFIX}/datasets/{settings.dataset}/upload/"
    with ExitStack() as stack:
        files = [
            ("files", (path.name, stack.enter_context(path.open("rb")))) for path in settings.files
        ]
        response = session.post(
            url,
            files=files,
            headers=mutation_headers(session, settings.base_url),
            timeout=settings.timeout_seconds,
        )
    payload = response_payload(response)
    if response.status_code not in (200, 201, 422):
        save_payload(settings.output, {"stage": "upload", "response": payload})
        response.raise_for_status()

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    accepted = data.get("accepted") if isinstance(data.get("accepted"), list) else []
    rejected = data.get("rejected") if isinstance(data.get("rejected"), list) else []
    document_ids = list(
        dict.fromkeys(
            str(item["id"]) for item in accepted if isinstance(item, dict) and item.get("id")
        )
    )
    reused = (
        data.get("reused_document_ids") if isinstance(data.get("reused_document_ids"), list) else []
    )
    print(
        f"Upload: {len(document_ids)} accepted ({len(reused)} already present), "
        f"{len(rejected)} rejected."
    )
    if rejected or not document_ids:
        save_payload(settings.output, {"stage": "upload", "response": payload})
        raise SystemExit(
            "The workflow was not invoked because at least one upload was rejected. "
            f"Details and accepted document IDs were saved to {settings.output}."
        )
    return document_ids


def invoke_documents(
    settings: Settings,
    session: requests.Session,
    document_ids: list[str],
) -> requests.Response:
    url = f"{settings.base_url}{API_PREFIX}/workflows/{settings.workflow}/invoke/"
    return session.post(
        url,
        json={
            "dataset": settings.dataset,
            "document_ids": document_ids,
            "name": settings.name,
            "client_reference": settings.client_reference,
        },
        headers=mutation_headers(session, settings.base_url)
        | {"Idempotency-Key": settings.idempotency_key},
        timeout=settings.timeout_seconds,
    )


def invoke_multipart(settings: Settings, session: requests.Session) -> requests.Response:
    """Convenience route; document-first invocation is easier to resume and inspect."""
    url = f"{settings.base_url}{API_PREFIX}/workflows/{settings.workflow}/invoke/"
    with ExitStack() as stack:
        files = [
            ("files", (path.name, stack.enter_context(path.open("rb")))) for path in settings.files
        ]
        return session.post(
            url,
            data={
                "dataset": settings.dataset,
                "name": settings.name,
                "client_reference": settings.client_reference,
            },
            files=files,
            headers=mutation_headers(session, settings.base_url)
            | {"Idempotency-Key": settings.idempotency_key},
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
    """Poll with private conditional requests until the bounded manifest is terminal."""
    accepted = response_payload(response)
    if response.status_code != 202:
        save_payload(settings.output, {"stage": "invoke", "response": accepted})
        response.raise_for_status()
        raise SystemExit(f"Expected HTTP 202 from workflow invocation; got {response.status_code}.")

    data = accepted.get("data") if isinstance(accepted.get("data"), dict) else {}
    results_url = str((data.get("links") or {}).get("results") or "")
    run_id = str(data.get("run_id") or "")
    if not results_url:
        raise SystemExit("Workflow acceptance response did not contain links.results.")
    require_same_origin(settings.base_url, results_url)

    deadline = time.monotonic() + settings.timeout_seconds
    etag = ""
    delay = retry_after_seconds(response)
    while True:
        if time.monotonic() + delay > deadline:
            save_payload(settings.output, {"stage": "accepted", "response": accepted})
            raise SystemExit(
                f"Timed out waiting for run {run_id}. Its operation handle was saved to "
                f"{settings.output}; poll {results_url} instead of resubmitting with a new key."
            )
        print(f"Run {run_id} is still processing; polling again in {delay:g}s...")
        time.sleep(delay)
        headers = {"If-None-Match": etag} if etag else None
        response = session.get(results_url, headers=headers, timeout=30)
        delay = retry_after_seconds(response)
        if response.status_code == 304:
            continue
        payload = response_payload(response)
        if response.status_code not in (200, 202):
            save_payload(settings.output, {"stage": "poll", "response": payload})
            response.raise_for_status()
        etag = response.headers.get("ETag", "")
        manifest = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if manifest.get("completed"):
            return payload


def fetch_paginated_collection(
    settings: Settings,
    session: requests.Session,
    url: str,
) -> list[dict[str, Any]]:
    """Follow DRF pagination links while keeping credentials on the configured origin."""
    items: list[dict[str, Any]] = []
    visited: set[str] = set()
    next_url: str | None = url
    while next_url:
        require_same_origin(settings.base_url, next_url)
        if next_url in visited:
            raise SystemExit(f"Pagination loop detected at {next_url}")
        visited.add(next_url)
        response = session.get(next_url, timeout=30)
        payload = response_payload(response)
        response.raise_for_status()
        page = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        results = page.get("results")
        if not isinstance(results, list):
            raise SystemExit(f"Paginated response at {next_url} did not contain data.results.")
        items.extend(item for item in results if isinstance(item, dict))
        candidate = page.get("next")
        next_url = str(candidate) if candidate else None
    return items


def fetch_result_collections(
    settings: Settings,
    session: requests.Session,
    manifest_payload: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    manifest = manifest_payload.get("data")
    links = manifest.get("links") if isinstance(manifest, dict) else None
    if not isinstance(links, dict):
        raise SystemExit("Run manifest did not contain collection links.")
    return {
        name: fetch_paginated_collection(settings, session, str(links[name]))
        for name in PAGINATED_RESOURCES
        if links.get(name)
    }


def print_summary(result: dict[str, Any], output: Path) -> None:
    manifest = result["manifest"]["data"]
    counts = manifest.get("counts") or {}
    collections = result.get("collections") or {}
    print()
    print(f"Run ID: {manifest['run_id']}")
    print(f"Status: {manifest['status']}")
    print(f"Workflow: {manifest['workflow']['name']} v{manifest['workflow']['version']}")
    print(f"Fields: {counts.get('fields', len(collections.get('fields') or []))}")
    print(
        "Classifications: "
        f"{counts.get('classifications', len(collections.get('classifications') or []))}"
    )
    print(f"Segments: {counts.get('segments', len(collections.get('segments') or []))}")
    print(f"Errors: {(manifest.get('errors') or {}).get('count', 0)}")
    print(f"Saved manifest and paginated results: {output}")


def print_dry_run(settings: Settings) -> None:
    body: dict[str, Any] = {
        "dataset": settings.dataset,
        "name": settings.name,
        "client_reference": settings.client_reference,
    }
    print("Dry run only. No authentication or data changes will be made.")
    if settings.resume_replay:
        print("Explicit resume/replay mode: approved-contract preflight and upload are skipped.")
    else:
        print(f"1. GET {settings.base_url}{API_PREFIX}/workflows/{settings.workflow}/contract/")
    if settings.document_ids:
        body["document_ids"] = settings.document_ids
        print("Existing documents would be invoked using JSON.")
    elif settings.multipart_invoke:
        body["files"] = [str(path) for path in settings.files]
        print("Multipart convenience invocation is enabled.")
    else:
        print(f"2. POST {settings.base_url}{API_PREFIX}/datasets/{settings.dataset}/upload/")
        print("   files=" + json.dumps([str(path) for path in settings.files]))
        body["document_ids"] = ["<document IDs returned by upload>"]
    step = (
        1
        if settings.resume_replay
        else 3
        if settings.files and not settings.multipart_invoke
        else 2
    )
    print(f"{step}. POST {settings.base_url}{API_PREFIX}/workflows/{settings.workflow}/invoke/")
    print(f"Idempotency-Key: {settings.idempotency_key}")
    print(json.dumps(body, indent=2))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="Files to upload and process.")
    parser.add_argument("--config", type=Path, help="JSON config file.")
    parser.add_argument("--base-url")
    parser.add_argument("--username")
    parser.add_argument("--password", help="Optional. If omitted, you will be prompted.")
    parser.add_argument("--workflow", help="Pinned, approved workflow-version UUID.")
    parser.add_argument("--dataset", help="Dataset UUID in the workflow project.")
    parser.add_argument("--name", help="Optional run name.")
    parser.add_argument("--client-reference", help="Optional caller-owned job or case reference.")
    parser.add_argument("--document-id", action="append", dest="document_ids")
    parser.add_argument("--output")
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument(
        "--idempotency-key",
        help="Reuse this value only when retrying the same logical invocation within 30 days.",
    )
    parser.add_argument(
        "--multipart-invoke",
        action="store_true",
        help="Upload through the invoke endpoint instead of the recommended document-first flow.",
    )
    parser.add_argument(
        "--resume-replay",
        action="store_true",
        help=(
            "Replay an original document-ID invocation without contract preflight or upload. "
            "Requires the exact original IDs, key, name, and client reference."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the requests that would be made without signing in or changing data.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    settings = build_settings(parse_args(argv or sys.argv[1:]))
    if settings.dry_run:
        print_dry_run(settings)
        return 0
    session = sign_in(settings)
    print(f"Idempotency-Key: {settings.idempotency_key}")
    if not settings.resume_replay:
        fetch_workflow_contract(settings, session)
    if settings.resume_replay:
        response = invoke_documents(settings, session, settings.document_ids)
    elif settings.multipart_invoke:
        response = invoke_multipart(settings, session)
    else:
        document_ids = settings.document_ids or upload_documents(settings, session)
        response = invoke_documents(settings, session, document_ids)
    manifest = wait_for_result(settings, session, response)
    result = {
        "manifest": manifest,
        "collections": fetch_result_collections(settings, session, manifest),
    }
    save_payload(settings.output, result)
    print_summary(result, settings.output)
    return 0 if manifest["data"]["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
