"""Configurable normalization used by matching, evaluation and export. Raw
values are never replaced — normalized forms are stored alongside."""

from __future__ import annotations

import re

from dateutil import parser as dateparser

from .collections import canonical_list

DEFAULT_NORMALIZATION = {
    "whitespace": True,
    "case": True,
    "punctuation": True,
    "dates": True,
    "currency": True,
    "percent": True,
    "phone": True,
    "identifiers": True,
    "numeric_precision": 2,
    "addresses": True,
}

_ADDR_ABBR = {
    "street": "st",
    "avenue": "ave",
    "road": "rd",
    "boulevard": "blvd",
    "suite": "ste",
    "drive": "dr",
    "lane": "ln",
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
}


def normalize_value(value, field_type: str = "string", cfg: dict | None = None) -> str | None:
    if value is None:
        return None
    if field_type == "list":
        try:
            return canonical_list(value)
        except ValueError:
            return None
    cfg = {**DEFAULT_NORMALIZATION, **(cfg or {})}
    s = str(value)
    if cfg["whitespace"]:
        s = " ".join(s.split())
    if field_type in ("date",) and cfg["dates"]:
        try:
            return dateparser.parse(s, fuzzy=True).date().isoformat()
        except (ValueError, OverflowError, TypeError):
            pass
    if field_type in ("currency", "number", "integer") and cfg["currency"]:
        neg = "(" in s and ")" in s or s.strip().startswith("-")
        num = re.sub(r"[^\d.]", "", s)
        if num and num.count(".") <= 1:
            try:
                f = float(num) * (-1 if neg else 1)
                prec = cfg["numeric_precision"]
                return f"{f:.{prec}f}" if field_type != "integer" else str(int(round(f)))
            except ValueError:
                pass
    if field_type == "percent" and cfg["percent"]:
        num = re.sub(r"[^\d.]", "", s)
        if num:
            try:
                return f"{float(num):.{cfg['numeric_precision']}f}"
            except ValueError:
                pass
    if field_type in ("identifier",) and cfg["identifiers"]:
        return re.sub(r"[^A-Za-z0-9]", "", s).upper()
    if field_type == "phone" and cfg["phone"]:
        d = re.sub(r"\D", "", s)
        return d[-10:] if len(d) >= 10 else d
    if field_type == "boolean":
        answer = s.strip().lower()
        if answer in ("true", "yes", "y", "1", "checked", "selected"):
            return "true"
        if answer in ("false", "no", "n", "0", "unchecked", "unselected"):
            return "false"
        return None
    if field_type == "address" and cfg["addresses"]:
        s2 = s.lower()
        for k, v in _ADDR_ABBR.items():
            s2 = re.sub(rf"\b{k}\b", v, s2)
        s = s2
    if cfg["case"]:
        s = s.lower()
    if cfg["punctuation"]:
        s = re.sub(r"[^\w\s]", "", s)
    return " ".join(s.split())


def values_match(
    truth,
    pred,
    field_type: str = "string",
    match_mode: str = "auto",
    cfg: dict | None = None,
    numeric_tolerance: float = 0.01,
    fuzzy_threshold: int = 92,
) -> bool:
    """Exact-after-normalization by default; numeric within tolerance; fuzzy by ratio."""
    from rapidfuzz import fuzz

    if truth in (None, "") and pred in (None, ""):
        return True
    if truth in (None, "") or pred in (None, ""):
        return False
    if field_type == "list":
        list_a, list_b = normalize_value(truth, "list"), normalize_value(pred, "list")
        return list_a is not None and list_b is not None and list_a == list_b
    if field_type == "boolean":
        bool_a, bool_b = normalize_value(truth, "boolean"), normalize_value(pred, "boolean")
        return bool_a is not None and bool_b is not None and bool_a == bool_b
    mode = match_mode
    if mode == "auto":
        mode = {
            "currency": "numeric",
            "number": "numeric",
            "integer": "numeric",
            "percent": "numeric",
            "date": "date",
            "identifier": "digits",
        }.get(field_type, "exact")
    if mode == "digits":
        return re.sub(r"\D", "", str(truth)) == re.sub(r"\D", "", str(pred)) and bool(
            re.sub(r"\D", "", str(truth))
        )
    if mode == "numeric":
        try:
            a, b = (
                float(re.sub(r"[^\d.\-]", "", str(truth))),
                float(re.sub(r"[^\d.\-]", "", str(pred))),
            )
            return abs(a - b) <= numeric_tolerance * max(1.0, abs(a))
        except ValueError:
            return False
    if mode == "date":
        return normalize_value(truth, "date", cfg) == normalize_value(pred, "date", cfg)
    if mode == "fuzzy":
        return (
            fuzz.ratio(
                normalize_value(truth, "string", cfg) or "",
                normalize_value(pred, "string", cfg) or "",
            )
            >= fuzzy_threshold
        )
    return normalize_value(truth, field_type, cfg) == normalize_value(pred, field_type, cfg)
