"""Command entry point and root options shared by every command."""

from __future__ import annotations

import sys
from collections.abc import Sequence

import click
import typer

from docai_cli import __version__
from docai_cli.client import DocAIClient
from docai_cli.commands import State, app
from docai_cli.errors import CliError
from docai_cli.output import diagnostic, emit_human_error, emit_json

_GLOBAL_FLAGS = {"--json", "--no-color", "--debug", "--utc", "--password-stdin", "--version"}
_GLOBAL_VALUES = {"--base-url", "--request-timeout", "--auth", "--username"}
_VALUE_OPTIONS = {
    "--base-url",
    "--request-timeout",
    "--timeout",
    "--auth",
    "--username",
    "--workflow",
    "--dataset",
    "--document-id",
    "--name",
    "--client-reference",
    "--idempotency-key",
    "--project",
    "--type",
    "--status",
    "--page",
    "--limit",
    "--run",
    "--format",
    "--output",
}


@app.callback(invoke_without_command=True)
def initialize(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show the CLI version and exit."),
    base_url: str = typer.Option(
        "http://127.0.0.1:8000",
        "--base-url",
        envvar="DOCAI_BASE_URL",
        help="Django API origin (not the Vite port). Defaults to local Django.",
    ),
    request_timeout: float = typer.Option(
        30, "--request-timeout", min=0.1, help="Per-HTTP-request timeout in seconds."
    ),
    auth: str = typer.Option(
        "session", "--auth", envvar="DOCAI_AUTH", help="Authentication mode: session or basic."
    ),
    username: str | None = typer.Option(None, "--username", envvar="DOCAI_USERNAME"),
    password_stdin: bool = typer.Option(
        False, "--password-stdin", help="Read one password line from stdin."
    ),
    json_mode: bool = typer.Option(False, "--json", help="Emit one JSON object on stdout."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable terminal color."),
    debug: bool = typer.Option(False, "--debug", help="Include safe error details."),
    utc: bool = typer.Option(False, "--utc", help="Show timestamps in UTC."),
) -> None:
    """DocAI command-line client. Use `docai <group> --help` to discover commands."""
    if version:
        typer.echo(f"docai {__version__}")
        raise typer.Exit()
    try:
        client = DocAIClient(
            base_url,
            request_timeout,
            username=username,
            password_stdin=password_stdin,
            auth_mode=auth,
        )
    except CliError as exc:
        if json_mode:
            emit_json(
                error={"code": exc.error_code, "message": exc.message},
                trace_id=exc.trace_id,
                operation=exc.operation,
            )
        else:
            emit_human_error(exc, debug=debug, no_color=no_color)
        raise typer.Exit(exc.exit_code) from exc
    ctx.obj = State(client=client, json_mode=json_mode, debug=debug, no_color=no_color, utc=utc)
    ctx.call_on_close(client.close)


def _normalize_global_options(args: Sequence[str]) -> list[str]:
    """Allow shared presentation/auth options before or after nested commands."""
    leading: list[str] = []
    remaining: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token in _GLOBAL_FLAGS:
            leading.append(token)
        elif token in _GLOBAL_VALUES and index + 1 < len(args):
            leading.extend((token, args[index + 1]))
            index += 1
        elif any(token.startswith(f"{option}=") for option in _GLOBAL_VALUES):
            leading.append(token)
        elif token in _VALUE_OPTIONS and index + 1 < len(args):
            remaining.extend((token, args[index + 1]))
            index += 1
        elif token == "--":
            remaining.extend(args[index:])
            break
        else:
            remaining.append(token)
        index += 1
    return [*leading, *remaining]


def main() -> None:
    arguments = _normalize_global_options(sys.argv[1:])
    json_mode = "--json" in arguments or any(arg.startswith("--json=") for arg in arguments)
    no_color = "--no-color" in arguments
    try:
        exit_code = app(args=arguments, prog_name="docai", standalone_mode=False)
        # Click returns Exit codes when standalone_mode=False instead of raising them.
        # Propagating that status is essential for scripts that rely on deterministic exits.
        if isinstance(exit_code, int):
            raise SystemExit(exit_code)
    except CliError as exc:
        # CLI commands normally format their own errors. This protects startup and cleanup edges.
        if json_mode:
            emit_json(
                data=exc.data,
                error={"code": exc.error_code, "message": exc.message, "details": exc.details},
                trace_id=exc.trace_id,
                operation=exc.operation,
                retryable=exc.retryable,
            )
        else:
            emit_human_error(exc, no_color=no_color)
        raise SystemExit(exc.exit_code) from exc
    except click.ClickException as exc:
        if json_mode:
            option = getattr(exc, "option_name", None)
            parameter = getattr(getattr(exc, "param", None), "name", None)
            message = "Invalid command arguments."
            if parameter:
                message = f"Invalid or missing value for '{parameter}'."
            elif option:
                message = f"Unknown option '{option}'."
            emit_json(
                error={"code": "CLI_USAGE_ERROR", "message": message},
                operation={"parameter": parameter, "option": option},
            )
        else:
            exc.show()
        raise SystemExit(2) from exc
    except click.exceptions.Exit as exc:
        raise SystemExit(exc.exit_code) from exc
    except click.Abort:
        if json_mode:
            emit_json(error={"code": "INTERRUPTED", "message": "Interrupted by user."})
        else:
            diagnostic("Interrupted by user.", error=True, no_color=no_color)
        raise SystemExit(130) from None
    except KeyboardInterrupt:
        if json_mode:
            emit_json(error={"code": "INTERRUPTED", "message": "Interrupted by user."})
        else:
            diagnostic("Interrupted by user.", error=True, no_color=no_color)
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
