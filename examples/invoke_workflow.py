"""Upload documents to a workflow and save its JSON response."""

import argparse
import json
import time
from contextlib import ExitStack
from getpass import getpass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import requests


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--workflow", required=True)
    p.add_argument("--dataset", required=True)
    p.add_argument("--username", required=True)
    p.add_argument("--output", default="result.json")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument(
        "--idempotency-key",
        default=None,
        help="Reuse this value only when retrying the same logical invocation.",
    )
    p.add_argument("files", nargs="+", type=Path)
    a = p.parse_args()
    idempotency_key = a.idempotency_key or str(uuid4())
    print(f"Idempotency-Key: {idempotency_key}")
    base = a.base_url.rstrip("/")
    session = requests.Session()
    response = session.get(base + "/api/v1/auth/session/", timeout=30)
    response.raise_for_status()
    response = session.post(
        base + "/api/v1/auth/login/",
        json={"username": a.username, "password": getpass("Password: ")},
        headers={"X-CSRFToken": session.cookies["csrftoken"], "Origin": base},
        timeout=30,
    )
    response.raise_for_status()
    with ExitStack() as stack:
        files = [("files", (path.name, stack.enter_context(path.open("rb")))) for path in a.files]
        response = session.post(
            base + f"/api/v1/workflows/{a.workflow}/invoke/",
            data={"dataset": a.dataset},
            files=files,
            headers={
                "X-CSRFToken": session.cookies["csrftoken"],
                "Origin": base,
                "Idempotency-Key": idempotency_key,
            },
            timeout=a.timeout,
        )
    deadline = time.monotonic() + a.timeout
    while True:
        payload = response.json()
        if response.status_code not in (200, 202):
            Path(a.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
            response.raise_for_status()
        data = payload["data"]
        if data["completed"]:
            break
        if time.monotonic() >= deadline:
            Path(a.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
            raise SystemExit(
                "Timed out waiting. Run ID and results URL saved; do not resubmit POST."
            )
        url = data["results_url"]
        if (urlsplit(url).scheme, urlsplit(url).netloc) != (
            urlsplit(base).scheme,
            urlsplit(base).netloc,
        ):
            raise SystemExit("Results URL does not match the configured server.")
        time.sleep(int(response.headers.get("Retry-After", "2")))
        response = session.get(url, timeout=30)
    Path(a.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Run {data['run_id']}: {data['status']}. JSON saved to {a.output}")
    if data["status"] != "succeeded":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
