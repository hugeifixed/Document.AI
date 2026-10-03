"""Field validation rules: regex, required, allowed values, numeric/date/percent
ranges, cross-field arithmetic/logic, and an external-reference adapter
placeholder. Predictions are never modified: the validator returns status,
messages, and an optional suggested correction stored separately."""

from __future__ import annotations

import operator
import re
from dataclasses import dataclass, field

from .collections import LIST_INVALID, parse_list
from .normalize import normalize_value
from .regex_safety import validate_regex

_OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


@dataclass
class ValidationOutcome:
    status: str = "passed"  # passed|failed|warning|not_run
    messages: list[str] = field(default_factory=list)
    suggested_correction: str | None = None


def _num(v):
    try:
        return float(re.sub(r"[^\d.\-]", "", str(v)))
    except (ValueError, TypeError):
        return None


def validate_field(
    name: str, value, rules: list[dict], all_values: dict, field_type: str = "string"
) -> ValidationOutcome:
    out = ValidationOutcome()
    if (
        field_type == "boolean"
        and value not in (None, "")
        and normalize_value(value, "boolean") is None
    ):
        return ValidationOutcome(
            status="failed", messages=[f"{name} does not contain a recognized boolean answer."]
        )
    if field_type == "list" and value not in (None, ""):
        try:
            entries = parse_list(value)
        except ValueError:
            return ValidationOutcome(status="failed", messages=[LIST_INVALID])
        if not entries and any(r.get("kind") == "required" for r in rules):
            return ValidationOutcome(
                status="failed", messages=[f"{name} requires at least one entry."]
            )
    for rule in rules or []:
        kind = rule.get("kind")
        sev = rule.get("severity", "failed")
        if kind == "required":
            if value in (None, ""):
                out.messages.append(rule.get("message") or f"{name} is required but was not found.")
                out.status = sev
        elif value in (None, ""):
            continue
        elif kind == "regex":
            if not validate_regex(rule["pattern"]).search(str(value)):
                out.messages.append(
                    rule.get("message") or f"{name} does not match the expected format."
                )
                out.status = _worse(out.status, sev)
        elif kind == "allowed_values":
            allowed = {str(a).lower() for a in rule.get("values", [])}
            if str(value).lower() not in allowed:
                out.messages.append(
                    rule.get("message") or f"{name} is not one of the allowed values."
                )
                out.status = _worse(out.status, sev)
        elif kind == "range":
            n = _num(value)
            lo, hi = rule.get("min"), rule.get("max")
            if n is None or (lo is not None and n < lo) or (hi is not None and n > hi):
                out.messages.append(rule.get("message") or f"{name} is outside the allowed range.")
                out.status = _worse(out.status, sev)
        elif kind == "date_range":
            d = normalize_value(value, "date")
            if (
                not d
                or (rule.get("min") and d < rule["min"])
                or (rule.get("max") and d > rule["max"])
            ):
                out.messages.append(
                    rule.get("message") or f"{name} is outside the allowed date range."
                )
                out.status = _worse(out.status, sev)
        elif kind == "cross_field":
            # e.g. {"kind":"cross_field","expr":"wages_box1 >= federal_tax","tolerance":0.01}
            ok = _eval_cross(rule["expr"], all_values, rule.get("tolerance", 0.0))
            if ok is False:
                out.messages.append(
                    rule.get("message") or f"Cross-field check failed: {rule['expr']}"
                )
                out.status = _worse(out.status, sev)
        elif kind == "external_reference":
            # placeholder adapter: records that an external check is pending; never blocks
            out.messages.append(
                f"External reference check '{rule.get('adapter', 'unknown')}' not executed (placeholder)."
            )
            out.status = _worse(out.status, "warning")
        elif kind == "suggest_normalized":
            nv = normalize_value(value, field_type)
            if nv and nv != str(value):
                out.suggested_correction = nv
    return out


def _worse(cur, new):
    order = {"passed": 0, "warning": 1, "failed": 2}
    return new if order.get(new, 0) > order.get(cur, 0) else cur


def _eval_cross(expr: str, values: dict, tol: float):
    """Supports  A op B  and  A op B + C / B - C / B * k  with numeric fields."""
    m = re.match(r"^\s*([\w.]+)\s*(==|!=|>=|<=|>|<)\s*(.+)$", expr)
    if not m:
        return None
    left, op, right = m.groups()
    lv = _num(values.get(left))
    rv = _eval_arith(right, values)
    if lv is None or rv is None:
        return None
    if op in ("==", "!="):
        eq = abs(lv - rv) <= tol * max(1.0, abs(rv))
        return eq if op == "==" else not eq
    return _OPS[op](lv, rv)


def _eval_arith(s: str, values: dict):
    toks = re.findall(r"[\w.]+|[+\-*/]", s)
    if not toks:
        return None

    def val(t):
        return _num(t) if re.match(r"^[\d.]+$", t) else _num(values.get(t))

    acc = val(toks[0])
    i = 1
    while i < len(toks) - 1 and acc is not None:
        op, v = toks[i], val(toks[i + 1])
        if v is None:
            return None
        acc = {"+": acc + v, "-": acc - v, "*": acc * v, "/": (acc / v if v else None)}[op]
        i += 2
    return acc
