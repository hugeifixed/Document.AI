"""Merge per-chunk extraction results into one result per field with an
explicit, recorded policy. Conflicts are surfaced, never silently resolved
away: the losing candidates are kept in `candidates`."""

from __future__ import annotations

from dataclasses import dataclass, field

from docai.schemas.llm import FieldOut


@dataclass
class ReconciledField:
    field: FieldOut
    policy: str
    candidates: list[FieldOut] = field(default_factory=list)
    conflict: bool = False


def _norm(v):
    return " ".join((v or "").split()).lower()


def reconcile(per_chunk: list[list[FieldOut]], policy: str) -> dict[str, ReconciledField]:
    by_name: dict[str, list[FieldOut]] = {}
    for fields in per_chunk:
        for f in fields:
            by_name.setdefault(f.name, []).append(f)
    out: dict[str, ReconciledField] = {}
    for name, cands in by_name.items():
        non_null = [c for c in cands if c.value not in (None, "")]
        distinct = {_norm(c.value) for c in non_null}
        conflict = len(distinct) > 1
        if not non_null:
            out[name] = ReconciledField(cands[0], policy, cands, False)
            continue
        if policy == "first_non_null":
            chosen = non_null[0]
        elif policy == "majority":
            counts: dict[str, int] = {}
            for c in non_null:
                counts[_norm(c.value)] = counts.get(_norm(c.value), 0) + 1
            top = max(counts.items(), key=lambda kv: kv[1])[0]
            chosen = max(
                (c for c in non_null if _norm(c.value) == top), key=lambda c: c.confidence or 0
            )
        elif policy == "conflicts_to_review":
            chosen = max(non_null, key=lambda c: c.confidence or 0)
            if conflict:
                chosen = chosen.model_copy(update={"confidence": 0.0})  # forces review routing
        else:  # highest_score
            chosen = max(non_null, key=lambda c: c.confidence or 0)
        out[name] = ReconciledField(chosen, policy, cands, conflict)
    return out
