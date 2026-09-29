"""Curated command groups for the REST operations used by automation."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import typer

from docai_cli.client import DocAIClient
from docai_cli.errors import EXIT_TIMEOUT, CliError
from docai_cli.output import (
    emit_detail,
    emit_json,
    emit_rows,
    emit_run_completion,
    run_status,
    transfer_status,
)


@dataclass
class State:
    client: DocAIClient
    json_mode: bool
    debug: bool
    no_color: bool
    utc: bool


def state(ctx: typer.Context) -> State:
    value = ctx.find_root().obj
    if not isinstance(value, State):
        raise RuntimeError("DocAI CLI was not initialized")
    return value


def perform(ctx: typer.Context, action: Callable[[State], None]) -> None:
    current = state(ctx)
    try:
        action(current)
    except CliError as exc:
        if current.json_mode:
            error = {"code": exc.error_code, "message": exc.message, "details": exc.details}
            emit_json(
                data=exc.data,
                error=error,
                trace_id=exc.trace_id,
                operation=exc.operation,
                retryable=exc.retryable,
            )
        else:
            from docai_cli.output import emit_human_error

            emit_human_error(exc, debug=current.debug, no_color=current.no_color)
        current.client.close()
        raise typer.Exit(code=exc.exit_code) from exc
    else:
        current.client.close()


def success(ctx: typer.Context, data: Any) -> None:
    current = state(ctx)
    emit_detail(data, json_mode=current.json_mode, no_color=current.no_color, utc=current.utc)


def list_command(
    ctx: typer.Context,
    resource: str,
    *,
    page: int,
    limit: int,
    all_pages: bool,
    id_only: bool,
    filters: dict[str, str] | None = None,
) -> None:
    current = state(ctx)
    query = urlencode(filters or {})
    path = resource + (f"?{query}" if query else "")
    rows = current.client.list_all(path, page=page, limit=limit, all_pages=all_pages)
    emit_rows(
        rows,
        json_mode=current.json_mode,
        id_only=id_only,
        no_color=current.no_color,
        utc=current.utc,
        kind=resource.rstrip("/"),
    )


app = typer.Typer(
    no_args_is_help=True,
    help="DocAI HTTP client for people, services, and agents.",
    pretty_exceptions_enable=False,
    pretty_exceptions_show_locals=False,
)
auth_app = typer.Typer(no_args_is_help=True, help="Inspect the current API identity.")
projects_app = typer.Typer(no_args_is_help=True, help="Browse projects.")
datasets_app = typer.Typer(no_args_is_help=True, help="Browse datasets and upload documents.")
workflows_app = typer.Typer(no_args_is_help=True, help="Browse callable workflow versions.")
documents_app = typer.Typer(no_args_is_help=True, help="Upload and browse stored documents.")
runs_app = typer.Typer(no_args_is_help=True, help="Submit and manage asynchronous runs.")
review_app = typer.Typer(no_args_is_help=True, help="Inspect fields awaiting human review.")
app.add_typer(auth_app, name="auth")
app.add_typer(projects_app, name="projects")
app.add_typer(datasets_app, name="datasets")
app.add_typer(workflows_app, name="workflows")
app.add_typer(documents_app, name="documents")
app.add_typer(runs_app, name="runs")
app.add_typer(review_app, name="review")


@app.command()
def health(ctx: typer.Context) -> None:
    """Check whether the Django API and its required dependencies are ready."""
    perform(ctx, lambda current: _health(ctx, current))


def _health(ctx: typer.Context, current: State) -> None:
    data, _ = current.client.get_json("health/ready/", api=False)
    success(ctx, data)


@auth_app.command("status")
def auth_status(ctx: typer.Context) -> None:
    """Show the authenticated account and its DocAI roles."""

    def action(current: State) -> None:
        data, _ = current.client.get_json("me/")
        success(ctx, data)

    perform(ctx, action)


@projects_app.command("list")
def projects_list(
    ctx: typer.Context,
    page: int = typer.Option(1, min=1, help="Page number."),
    limit: int = typer.Option(100, min=1, max=200, help="Items per page."),
    all_pages: bool = typer.Option(False, "--all", help="Read at most 1,000 pages."),
    id_only: bool = typer.Option(False, "--id-only", help="Print only full IDs."),
) -> None:
    """List projects visible to the authenticated user."""
    perform(
        ctx,
        lambda current: list_command(
            ctx, "projects/", page=page, limit=limit, all_pages=all_pages, id_only=id_only
        ),
    )


@datasets_app.command("list")
def datasets_list(
    ctx: typer.Context,
    project: str | None = typer.Option(None, "--project", help="Filter by project UUID."),
    page: int = typer.Option(1, min=1),
    limit: int = typer.Option(100, min=1, max=200),
    all_pages: bool = typer.Option(False, "--all"),
    id_only: bool = typer.Option(False, "--id-only"),
) -> None:
    """List datasets, optionally within one project."""
    filters = {"project": project} if project else None
    perform(
        ctx,
        lambda current: list_command(
            ctx,
            "datasets/",
            page=page,
            limit=limit,
            all_pages=all_pages,
            id_only=id_only,
            filters=filters,
        ),
    )


@workflows_app.command("list")
def workflows_list(
    ctx: typer.Context,
    project: str | None = typer.Option(None, "--project"),
    workflow_type: str | None = typer.Option(None, "--type"),
    status: str | None = typer.Option(None, "--status"),
    page: int = typer.Option(1, min=1),
    limit: int = typer.Option(100, min=1, max=200),
    all_pages: bool = typer.Option(False, "--all"),
    id_only: bool = typer.Option(False, "--id-only"),
) -> None:
    """List workflow versions; use the UUID of an approved version to invoke it."""
    filters = {
        key: value
        for key, value in (
            ("project", project),
            ("workflow_type", workflow_type),
            ("status", status),
        )
        if value
    }
    perform(
        ctx,
        lambda current: list_command(
            ctx,
            "workflows/",
            page=page,
            limit=limit,
            all_pages=all_pages,
            id_only=id_only,
            filters=filters,
        ),
    )


@workflows_app.command("contract")
def workflows_contract(
    ctx: typer.Context, workflow_id: str = typer.Argument(help="Approved workflow UUID.")
) -> None:
    """Fetch the public input/output contract for an approved workflow version."""

    def action(current: State) -> None:
        data, _ = current.client.get_json(f"workflows/{workflow_id}/contract/")
        success(ctx, data)

    perform(ctx, action)


@documents_app.command("list")
def documents_list(
    ctx: typer.Context,
    dataset: str = typer.Option(..., "--dataset", help="Dataset UUID."),
    page: int = typer.Option(1, min=1),
    limit: int = typer.Option(100, min=1, max=200),
    all_pages: bool = typer.Option(False, "--all"),
    id_only: bool = typer.Option(False, "--id-only"),
) -> None:
    """List documents in a dataset."""
    perform(
        ctx,
        lambda current: list_command(
            ctx,
            "documents/",
            page=page,
            limit=limit,
            all_pages=all_pages,
            id_only=id_only,
            filters={"dataset": dataset},
        ),
    )


@documents_app.command("upload")
def documents_upload(
    ctx: typer.Context,
    files: list[Path] = typer.Argument(..., exists=True, readable=True, dir_okay=False),
    dataset: str = typer.Option(..., "--dataset", help="Destination dataset UUID."),
) -> None:
    """Stream one or more files into a dataset and report accepted and rejected files."""

    def action(current: State) -> None:
        with transfer_status(
            f"Sending {len(files)} file{'s' if len(files) != 1 else ''}",
            json_mode=current.json_mode,
            no_color=current.no_color,
        ) as report:
            data, _ = current.client.upload(dataset, files, on_progress=report)
        success(ctx, data)

    perform(ctx, action)


@runs_app.command("submit")
def runs_submit(
    ctx: typer.Context,
    workflow: str = typer.Option(..., "--workflow", help="Approved workflow UUID."),
    dataset: str = typer.Option(..., "--dataset", help="Dataset UUID."),
    document_id: list[str] = typer.Option(..., "--document-id", help="Repeat for each document."),
    name: str = typer.Option("", "--name", help="Optional run name."),
    client_reference: str = typer.Option(
        "", "--client-reference", help="Caller-owned correlation ID."
    ),
    idempotency_key: str | None = typer.Option(
        None, "--idempotency-key", help="Persist this to safely replay the same request."
    ),
) -> None:
    """Submit selected documents and return an asynchronous run handle."""

    def action(current: State) -> None:
        key = idempotency_key or str(uuid.uuid4())
        payload = {
            "dataset": dataset,
            "document_ids": document_id,
            "name": name,
            "client_reference": client_reference,
        }
        try:
            data, _ = current.client.post_json(
                f"workflows/{workflow}/invoke/", payload, headers={"Idempotency-Key": key}
            )
        except CliError as exc:
            exc.operation = {
                **(exc.operation or {}),
                "workflow_id": workflow,
                "idempotency_key": key,
            }
            raise
        data = {**data, "idempotency_key": key}
        success(ctx, data)

    perform(ctx, action)


@runs_app.command("list")
def runs_list(
    ctx: typer.Context,
    project: str | None = typer.Option(None, "--project"),
    dataset: str | None = typer.Option(None, "--dataset"),
    status: str | None = typer.Option(None, "--status"),
    page: int = typer.Option(1, min=1),
    limit: int = typer.Option(100, min=1, max=200),
    all_pages: bool = typer.Option(False, "--all"),
    id_only: bool = typer.Option(False, "--id-only"),
) -> None:
    """List runs, optionally filtered by project, dataset, or status."""
    filters = {
        key: value
        for key, value in (("project", project), ("dataset", dataset), ("status", status))
        if value
    }
    perform(
        ctx,
        lambda current: list_command(
            ctx,
            "runs/",
            page=page,
            limit=limit,
            all_pages=all_pages,
            id_only=id_only,
            filters=filters,
        ),
    )


@runs_app.command("show")
def runs_show(ctx: typer.Context, run_id: str = typer.Argument(help="Run UUID.")) -> None:
    """Show persisted run state."""

    def action(current: State) -> None:
        data, _ = current.client.get_json(f"runs/{run_id}/")
        success(ctx, data)

    perform(ctx, action)


@runs_app.command("progress")
def runs_progress(ctx: typer.Context, run_id: str = typer.Argument(help="Run UUID.")) -> None:
    """Read detailed worker progress for a run."""

    def action(current: State) -> None:
        data, _ = current.client.get_json(f"runs/{run_id}/progress/")
        success(ctx, data)

    perform(ctx, action)


@runs_app.command("wait")
def runs_wait(
    ctx: typer.Context,
    run_id: str = typer.Argument(help="Run UUID."),
    timeout: int = typer.Option(300, min=1, help="Maximum seconds to poll."),
) -> None:
    """Poll the bounded manifest until terminal state or timeout."""

    def action(current: State) -> None:
        client = current.client
        started = time.monotonic()
        client.deadline = started + timeout
        url = f"runs/{run_id}/results/"
        etag: str | None = None
        last_data: Any = None
        with run_status(run_id, json_mode=current.json_mode, no_color=current.no_color) as report:
            while True:
                try:
                    headers = {"If-None-Match": etag} if etag else None
                    data, response = client.get_json(url, headers=headers)
                    etag = response.headers.get("ETag") or etag
                    if response.status_code != 304:
                        last_data = data
                        if isinstance(data, dict) and data.get("completed"):
                            break
                        if isinstance(data, dict):
                            report(data)
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise CliError(
                            "Polling timed out; the run continues on the server.",
                            EXIT_TIMEOUT,
                            "POLL_TIMEOUT",
                            operation={"run_id": run_id},
                            data=last_data,
                        )
                    delay = min(
                        _retry_after(response.headers.get("Retry-After"), fallback=2), remaining
                    )
                    time.sleep(delay)
                except CliError as exc:
                    if exc.exit_code == EXIT_TIMEOUT:
                        exc.operation = {**(exc.operation or {}), "run_id": run_id}
                        if exc.data is None:
                            exc.data = last_data
                    raise
        emit_run_completion(last_data, json_mode=current.json_mode)

    perform(ctx, action)


@runs_app.command("cancel")
def runs_cancel(ctx: typer.Context, run_id: str = typer.Argument(help="Run UUID.")) -> None:
    """Ask the server to stop unclaimed work; in-flight provider calls may finish."""

    def action(current: State) -> None:
        data, _ = current.client.post_json(f"runs/{run_id}/cancel/", {})
        success(ctx, data)

    perform(ctx, action)


@runs_app.command("retry")
def runs_retry(ctx: typer.Context, run_id: str = typer.Argument(help="Run UUID.")) -> None:
    """Retry failed items in an existing run."""

    def action(current: State) -> None:
        data, _ = current.client.post_json(f"runs/{run_id}/retry/", {})
        success(ctx, data)

    perform(ctx, action)


@runs_app.command("export")
def runs_export(
    ctx: typer.Context,
    run_id: str = typer.Argument(help="Run UUID."),
    format: str = typer.Option("json", "--format", case_sensitive=False),
    output: Path = typer.Option(..., "--output", help="Destination file."),
    force: bool = typer.Option(False, "--force", help="Replace an existing file."),
) -> None:
    """Download a complete JSON, CSV, or XLSX delivery package."""
    if format.lower() not in {"json", "csv", "xlsx"}:
        raise typer.BadParameter("Choose json, csv, or xlsx.", param_hint="--format")

    def action(current: State) -> None:
        with transfer_status(
            "Receiving export", json_mode=current.json_mode, no_color=current.no_color
        ) as report:
            current.client.download(
                f"runs/{run_id}/export/{format.lower()}/",
                output,
                force=force,
                on_progress=report,
            )
        success(ctx, {"run_id": run_id, "path": str(output), "format": format.lower()})

    perform(ctx, action)


@review_app.command("list")
def review_list(
    ctx: typer.Context,
    run: str | None = typer.Option(None, "--run", help="Filter by run UUID."),
    page: int = typer.Option(1, min=1),
    limit: int = typer.Option(100, min=1, max=200),
    all_pages: bool = typer.Option(False, "--all"),
    id_only: bool = typer.Option(False, "--id-only"),
) -> None:
    """List extracted fields whose review status needs human attention."""
    filters = {"review_status": "needs_review"}
    if run:
        filters["run"] = run
    perform(
        ctx,
        lambda current: list_command(
            ctx,
            "fields/",
            page=page,
            limit=limit,
            all_pages=all_pages,
            id_only=id_only,
            filters=filters,
        ),
    )


def _retry_after(value: str | None, *, fallback: float) -> float:
    try:
        return max(0.25, min(30.0, float(value))) if value is not None else fallback
    except ValueError:
        return fallback
