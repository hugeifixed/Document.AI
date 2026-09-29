"""Keep command data on stdout and diagnostics on stderr."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from rich.cells import cell_len
from rich.console import Console
from rich.filesize import decimal
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from docai_cli import __version__
from docai_cli.errors import CliError

_LIST_COLUMNS: dict[str, tuple[str, ...]] = {
    "projects": ("name", "slug", "modified", "id"),
    "datasets": ("name", "document_count", "modified", "id"),
    "workflows": ("name", "version", "workflow_type", "status", "id"),
    "documents": ("original_filename", "status", "page_count", "created", "id"),
    "runs": ("name", "status", "processed_items", "total_items", "created", "id"),
    "fields": ("document_name", "name", "review_status", "id"),
}
_COLUMN_MAX_WIDTH = {
    "name": 32,
    "original_filename": 38,
    "document_name": 32,
    "slug": 24,
    "workflow_type": 22,
}
_STATUS_STYLES = {
    "succeeded": "green",
    "completed": "green",
    "approved": "green",
    "failed": "red",
    "partial": "yellow",
    "processing": "cyan",
    "running": "cyan",
    "cancelled": "dim",
}


def emit_json(
    *,
    data: Any = None,
    error: Mapping[str, Any] | None = None,
    trace_id: str | None = None,
    operation: Mapping[str, Any] | None = None,
    retryable: bool | None = None,
) -> None:
    """Write exactly one compact, ordered JSON object for scripts and agents."""
    payload = {
        "success": error is None,
        "data": data,
        "error": error,
        "trace_id": trace_id,
        "operation": operation,
        "retryable": retryable,
        "cli_version": __version__,
    }
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
    )


def diagnostic(message: str, *, error: bool = False, no_color: bool = False) -> None:
    console = Console(stderr=True, **_console_options(no_color))
    console.print(message, style="red" if error else None, highlight=False, markup=False)


def _live_terminal() -> bool:
    return (
        sys.stdout.isatty()
        and sys.stderr.isatty()
        and os.environ.get("TERM") != "dumb"
        and not os.environ.get("CI")
    )


def _progress_console(*, no_color: bool) -> Console:
    # Terminal defaults and reverse video remain legible on light and dark backgrounds.
    return Console(stderr=True, highlight=False, **_console_options(no_color))


def _run_status_text(run_id: str, data: Mapping[str, Any]) -> str:
    status = _cell(data.get("stage") or data.get("status") or "waiting")
    parts = [f"Run {_cell(run_id[:8])}", status]
    counts = data.get("counts")
    items = counts.get("run_items") if isinstance(counts, dict) else None
    if isinstance(items, dict):
        total = items.get("total")
        if isinstance(total, int) and total > 1:
            done = sum(
                items[key]
                for key in ("succeeded", "failed", "skipped")
                if isinstance(items.get(key), int)
            )
            parts.append(f"{done}/{total} items")
        elif total == 1:
            parts.append("1 document")
        failed = items.get("failed")
        if isinstance(failed, int) and failed > 0:
            parts.append(f"{failed} failed")
    eta = data.get("estimated_seconds_remaining")
    if isinstance(eta, int) and eta >= 0:
        parts.append(f"ETA ~{eta}s")
    return " · ".join(parts)


@contextmanager
def run_status(
    run_id: str, *, json_mode: bool, no_color: bool = False
) -> Iterator[Callable[[Mapping[str, Any]], None]]:
    """Keep live wait output on stderr; log only changed states without a TTY."""
    if json_mode:
        yield lambda _data: None
        return
    if not _live_terminal():
        last_message: str | None = None

        def report(data: Mapping[str, Any]) -> None:
            nonlocal last_message
            message = _run_status_text(run_id, data)
            if message != last_message:
                diagnostic(message, no_color=no_color)
                last_message = message

        yield report
        return
    with Progress(
        SpinnerColumn(style="none"),
        TextColumn("{task.description}", markup=False),
        console=_progress_console(no_color=no_color),
        transient=True,
        redirect_stdout=False,
        redirect_stderr=False,
        refresh_per_second=4,
    ) as progress:
        task = progress.add_task(f"Run {_cell(run_id[:8])} · waiting", total=None)
        yield lambda data: progress.update(task, description=_run_status_text(run_id, data))


@contextmanager
def transfer_status(
    label: str, *, json_mode: bool, no_color: bool = False
) -> Iterator[Callable[[int, int | None], None] | None]:
    """Report bytes transferred, never implying that server processing is complete."""
    if json_mode or not _live_terminal():
        yield None
        return
    with Progress(
        SpinnerColumn(style="none"),
        TextColumn("{task.description}", markup=False),
        BarColumn(
            bar_width=18,
            style="none",
            complete_style="reverse",
            finished_style="reverse",
            pulse_style="none",
        ),
        TextColumn("{task.fields[detail]}", markup=False),
        console=_progress_console(no_color=no_color),
        transient=True,
        redirect_stdout=False,
        redirect_stderr=False,
        refresh_per_second=4,
    ) as progress:
        task = progress.add_task(label, total=None, detail="0 bytes")

        def report(sent: int, total: int | None) -> None:
            known_total = total if isinstance(total, int) and total > 0 else None
            detail = f"{decimal(sent)} / {decimal(known_total)}" if known_total else decimal(sent)
            progress.update(task, completed=sent, total=known_total, detail=detail)

        yield report


def emit_run_completion(data: Any, *, json_mode: bool) -> None:
    """Summarize a finished run for people; preserve its full manifest for agents."""
    if json_mode:
        emit_json(data=data)
        return
    if not isinstance(data, dict):
        emit_detail(data, json_mode=False)
        return
    run_id = _cell(data.get("run_id") or "")
    status = _cell(data.get("status") or "completed")
    lines = [f"Run {status}: {run_id}"]
    counts = data.get("counts")
    items = counts.get("run_items") if isinstance(counts, dict) else None
    failed = 0
    if isinstance(items, dict):
        parts = [
            f"{items[key]} {key}"
            for key in ("succeeded", "failed", "skipped")
            if isinstance(items.get(key), int) and items[key] > 0
        ]
        total = items.get("total")
        if isinstance(total, int):
            lines.append(f"  Items   {' · '.join(parts) if parts else 'none'} / {total} total")
        failed_value = items.get("failed")
        failed = failed_value if isinstance(failed_value, int) else 0
    review = data.get("review")
    review_total = review.get("total") if isinstance(review, dict) else None
    review_fields = review.get("fields") if isinstance(review, dict) else None
    if isinstance(review_total, int) and review_total > 0:
        lines.append(f"  Review  {review_total} need attention")
    if run_id:
        if failed:
            next_command = f"docai runs progress {run_id}"
        elif isinstance(review_fields, int) and review_fields > 0:
            next_command = f"docai review list --run {run_id}"
        elif isinstance(review_total, int) and review_total > 0:
            next_command = f"docai runs show {run_id}"
        elif status in {"succeeded", "partial"}:
            next_command = f"docai runs export {run_id} --format json --output results.json"
        else:
            next_command = f"docai runs show {run_id}"
        lines.append(f"  Next    {next_command}")
    sys.stdout.write("\n".join(lines) + "\n")


def color_disabled() -> bool:
    if os.environ.get("FORCE_COLOR") and os.environ["FORCE_COLOR"] not in {"0", "false", "False"}:
        return False
    return bool(os.environ.get("NO_COLOR")) or bool(os.environ.get("DOCAI_NO_COLOR"))


def _console_options(no_color: bool) -> dict[str, Any]:
    """Make explicit plain-text output stronger than Rich's color-only mode."""
    disabled = no_color or color_disabled()
    return {
        "no_color": disabled,
        # Rich's no_color retains bold/dim ANSI styles. A null color system
        # guarantees plain text while preserving table layout and live updates.
        "color_system": None if disabled else "auto",
    }


def emit_human_error(exc: CliError, *, debug: bool = False, no_color: bool = False) -> None:
    console = Console(stderr=True, **_console_options(no_color))
    console.print(f"error: {exc.message}", style="bold red", highlight=False, markup=False)
    console.print(f"  code: {exc.error_code}", style="dim", highlight=False, markup=False)
    if exc.error_code == "PARTIAL_UPLOAD_REJECTION" and isinstance(exc.data, dict):
        _emit_partial_upload(console, exc.data)
    if exc.operation:
        fields = ", ".join(f"{key}={_cell(value)}" for key, value in exc.operation.items())
        console.print(f"  operation: {fields}", style="dim", highlight=False, markup=False)
    if exc.trace_id:
        console.print(
            f"  trace_id: {_cell(exc.trace_id)}", style="dim", highlight=False, markup=False
        )
    if debug and exc.details:
        details = json.dumps(exc.details, ensure_ascii=False, default=str)
        console.print(f"  details: {details}", highlight=False, markup=False)


def _emit_partial_upload(console: Console, data: dict[str, Any]) -> None:
    accepted = data.get("accepted")
    rejected = data.get("rejected")
    reused_values = data.get("reused_document_ids")
    reused = {str(item) for item in reused_values} if isinstance(reused_values, list) else set()
    if isinstance(accepted, list) and accepted:
        console.print("  Accepted:", style="bold", highlight=False, markup=False)
        for item in accepted:
            if not isinstance(item, dict):
                continue
            identifier = str(item.get("id") or "")
            name = _cell(item.get("original_filename") or item.get("filename") or "Document")
            suffix = " (reused)" if identifier in reused else ""
            console.print(f"    {name}  {identifier}{suffix}", highlight=False, markup=False)
    if isinstance(rejected, list) and rejected:
        console.print("  Rejected:", style="bold", highlight=False, markup=False)
        for item in rejected:
            if not isinstance(item, dict):
                continue
            name = _cell(item.get("filename") or "File")
            code = _cell(item.get("error_code") or "REJECTED")
            message = _cell(item.get("message") or "Upload rejected")
            console.print(f"    {name}: {message} ({code})", highlight=False, markup=False)


def emit_detail(data: Any, *, json_mode: bool, no_color: bool = False, utc: bool = False) -> None:
    """Render details for a person while keeping the agent JSON envelope unchanged."""
    if json_mode:
        emit_json(data=data)
        return
    human_data = _humanize(data, utc=utc)
    if not isinstance(human_data, (dict, list)):
        sys.stdout.write(f"{_cell(human_data)}\n")
        return
    rendered = json.dumps(human_data, ensure_ascii=False, indent=2, default=str)
    if sys.stdout.isatty():
        console = Console(
            file=sys.stdout,
            width=shutil_terminal_width(),
            soft_wrap=True,
            **_console_options(no_color),
        )
        console.print_json(json=rendered, indent=2, ensure_ascii=False)
    else:
        sys.stdout.write(rendered + "\n")


def emit_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    json_mode: bool,
    id_only: bool = False,
    columns: tuple[str, ...] | None = None,
    no_color: bool = False,
    utc: bool = False,
    kind: str | None = None,
) -> None:
    materialized = [dict(row) for row in rows]
    if json_mode:
        emit_json(data=[row.get("id") for row in materialized] if id_only else materialized)
        return
    if id_only:
        for row in materialized:
            value = row.get("id")
            if value is not None:
                sys.stdout.write(f"{value}\n")
        return
    selected = columns or _columns(materialized, kind=kind)
    if not selected:
        sys.stdout.write(f"No {kind}.\n" if kind else "No results.\n")
        return
    if not sys.stdout.isatty():
        _emit_tsv(materialized, selected, utc=utc)
        return
    width = shutil_terminal_width()
    visible = list(selected)
    while width < _minimum_width(visible, materialized, utc=utc):
        removable = [key for key in visible if key not in {visible[0], "id"}]
        if not removable:
            _emit_tsv(materialized, selected, utc=utc)
            return
        visible.remove(removable[-1])
    table = Table(
        show_header=True,
        header_style="dim",
        box=None,
        show_edge=False,
        show_lines=False,
        expand=False,
        padding=(0, 1),
        caption=f"{len(materialized)} {kind[:-1] if len(materialized) == 1 else kind}"
        if kind
        else f"{len(materialized)} result{'s' if len(materialized) != 1 else ''}",
        caption_style="dim",
        caption_justify="left",
    )
    for key in visible:
        table.add_column(
            key.replace("_", " ").title(),
            style="dim" if key == "id" else None,
            overflow="fold" if key == "id" else "ellipsis",
            no_wrap=True,
            min_width=_column_width(key, materialized, utc=utc),
            max_width=_COLUMN_MAX_WIDTH.get(key),
        )
    for row in materialized:
        table.add_row(
            *[
                Text(
                    _display_cell(key, row.get(key), utc=utc),
                    style=_STATUS_STYLES.get(str(row.get(key)).lower(), "")
                    if key == "status"
                    else "",
                )
                for key in visible
            ]
        )
    Console(
        file=sys.stdout,
        width=width,
        soft_wrap=True,
        highlight=False,
        **_console_options(no_color),
    ).print(table)


def _emit_tsv(
    rows: list[dict[str, Any]], columns: tuple[str, ...] | list[str], *, utc: bool
) -> None:
    for row in rows:
        sys.stdout.write(
            "\t".join(_display_cell(key, row.get(key), utc=utc) for key in columns) + "\n"
        )


def _columns(rows: list[dict[str, Any]], *, kind: str | None = None) -> tuple[str, ...]:
    if not rows:
        return ()
    priority = _LIST_COLUMNS.get(
        kind or "",
        ("name", "original_filename", "status", "review_status", "modified", "created", "id"),
    )
    present = set().union(*(row.keys() for row in rows))
    chosen = tuple(key for key in priority if key in present)
    return chosen or tuple(rows[0])


def _column_width(key: str, rows: list[dict[str, Any]], *, utc: bool) -> int:
    label = key.replace("_", " ").title()
    width = max(
        cell_len(label),
        max((cell_len(_display_cell(key, row.get(key), utc=utc)) for row in rows), default=0),
    )
    return min(width, _COLUMN_MAX_WIDTH[key]) if key in _COLUMN_MAX_WIDTH else width


def _minimum_width(columns: list[str], rows: list[dict[str, Any]], *, utc: bool) -> int:
    # Reserve more than the table's two padding cells per column, keeping IDs intact.
    return sum(_column_width(key, rows, utc=utc) for key in columns) + 3 * len(columns)


def shutil_terminal_width() -> int:
    """Use detected width for TTY output and avoid Rich's implicit 80-column truncation."""
    import shutil

    return shutil.get_terminal_size(fallback=(200, 24)).columns


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    else:
        rendered = str(value)
    return "".join(" " if ord(char) < 32 or 127 <= ord(char) < 160 else char for char in rendered)


def _humanize(value: Any, *, utc: bool, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {name: _humanize(item, utc=utc, key=str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_humanize(item, utc=utc, key=key) for item in value]
    if isinstance(value, str) and key is not None and _is_timestamp_key(key):
        return _display_cell(key, value, utc=utc)
    return value


def _is_timestamp_key(key: str) -> bool:
    return key in {"created", "modified", "status_changed"} or key.endswith("_at")


def _display_cell(key: str, value: Any, *, utc: bool) -> str:
    rendered = _cell(value)
    if value is None or not _is_timestamp_key(key):
        return rendered
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return rendered
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC if utc else None).strftime("%Y-%m-%d %H:%M")
