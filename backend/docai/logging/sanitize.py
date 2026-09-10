"""Never log secrets, tokens, credentials, or PII. Applied to every record's
message and extra fields. Detection is pattern-based and deliberately eager."""
from __future__ import annotations

import re

_SECRET_KEYS = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|credential|"
    r"connection[_-]?string|cookie|session)", re.IGNORECASE)
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


def sanitize_extra(extra: dict) -> dict:
    out = {}
    for k, v in extra.items():
        if _SECRET_KEYS.search(str(k)):
            out[k] = "[REDACTED]"
        elif isinstance(v, str):
            out[k] = sanitize_text(v)[:500]
        elif isinstance(v, dict):
            out[k] = sanitize_extra(v)
        else:
            out[k] = v
    return out
