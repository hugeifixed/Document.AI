"""Never log secrets, tokens, credentials, or PII. Applied to every record's
message and extra fields. Detection is pattern-based and deliberately eager."""

from __future__ import annotations

import re
import traceback
from typing import Any


def exception_context(exc: Exception) -> dict[str, Any]:
    """Call locations and exception class, without payloads, locals or source lines."""
    frames = [
        f"{frame.f_globals.get('__name__', '')}.{frame.f_code.co_name}:{line}"
        for frame, line in traceback.walk_tb(exc.__traceback__)
    ]
    return {
        "exception_type": type(exc).__name__,
        "error_stack": " > ".join(frames[-8:]),
        "error_origin": frames[-1] if frames else "",
        **getattr(exc, "diagnostics", {}),
    }


_SECRET_KEYS = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|credential|"
    r"connection[_-]?string|cookie|session)",
    re.IGNORECASE,
)
_CORRELATION_KEYS = {
    "run_id",
    "item_id",
    "document_id",
    "dataset_id",
    "workflow_id",
    "project_id",
    "task_id",
    "trace_id",
    "provider_request_id",
}
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)
_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\b\d{2}-\d{7}\b"), "[EIN]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARD/ACCT]"),
    (re.compile(r"(?i)bearer\s+[a-z0-9\-._~+/]+=*"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"\b\d{9,}\b"), "[NUM]"),
]


def sanitize_text(text: str) -> str:
    if not text:
        return text
    for pat, rep in _PATTERNS:
        text = pat.sub(rep, text)
    return text


def sanitize_extra(extra: dict[Any, Any]) -> dict[Any, Any]:
    out: dict[Any, Any] = {}
    for k, v in extra.items():
        if _SECRET_KEYS.search(str(k)):
            out[k] = "[REDACTED]"
        elif isinstance(v, str):
            # Numeric UUID segments are identifiers, not account numbers. Exempt only
            # complete UUIDs in known correlation fields; arbitrary text stays redacted.
            out[k] = v if k in _CORRELATION_KEYS and _UUID.fullmatch(v) else sanitize_text(v)[:500]
        elif isinstance(v, dict):
            out[k] = sanitize_extra(v)
        else:
            out[k] = v
    return out
