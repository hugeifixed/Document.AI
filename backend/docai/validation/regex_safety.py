"""Static safety checks for user-supplied regex before it ever runs against
document text (catastrophic backtracking is a DoS vector in rule engines)."""

from __future__ import annotations

import re

from docai.exceptions import UnsafeRegex

MAX_PATTERN_LEN = 400
_NESTED_QUANT = re.compile(r"\((?:[^()\\]|\\.)*[+*][^()]*\)\s*[+*{]")  # (a+)+ , (a*)*  , (x+){2,}
_ADJ_QUANT = re.compile(r"[+*]\s*[+*]")  # a++ / a** (possessive-ish or double)
_OVERLAP_ALT = re.compile(
    r"\((?:[^()\\|]|\\.)+\|(?:[^()\\|]|\\.)+\)[+*]"
)  # (a|a)+ style repeated alternation


def validate_regex(pattern: str) -> re.Pattern:
    """Return the compiled pattern or raise UnsafeRegex with a plain reason."""
    if not pattern or len(pattern) > MAX_PATTERN_LEN:
        raise UnsafeRegex(errors={"pattern": f"empty or longer than {MAX_PATTERN_LEN} characters"})
    if "\\" in pattern and re.search(r"\\[1-9]", pattern):
        raise UnsafeRegex(errors={"pattern": "backreferences are not allowed"})
    if _NESTED_QUANT.search(pattern):
        raise UnsafeRegex(errors={"pattern": "nested quantifiers like (a+)+ are not allowed"})
    if _ADJ_QUANT.search(pattern):
        raise UnsafeRegex(errors={"pattern": "adjacent quantifiers are not allowed"})
    if _OVERLAP_ALT.search(pattern):
        raise UnsafeRegex(errors={"pattern": "repeated alternation groups are not allowed"})
    if pattern.count("(") > 20:
        raise UnsafeRegex(errors={"pattern": "too many groups"})
    try:
        compiled = re.compile(pattern, re.I | re.M)
    except re.error as exc:
        raise UnsafeRegex(errors={"pattern": f"invalid regex: {exc.msg}"}) from None
    return compiled
