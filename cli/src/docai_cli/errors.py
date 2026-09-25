"""Stable CLI errors and process exit codes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

EXIT_SUCCESS = 0
EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_AUTH = 4
EXIT_NOT_FOUND = 5
EXIT_SERVER = 6
EXIT_TIMEOUT = 7
EXIT_TRANSPORT = 8


@dataclass
class CliError(Exception):
    message: str
    exit_code: int
    error_code: str = "DOCAI_CLI_ERROR"
    trace_id: str | None = None
    details: Any = None
    operation: dict[str, Any] | None = None
    data: Any = None
    retryable: bool | None = None

    def __str__(self) -> str:
        return self.message
