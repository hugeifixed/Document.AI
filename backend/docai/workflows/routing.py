"""Review routing: first matching rule wins; default is human review for
anything without grounding or with a validation failure, else auto-accept."""

from __future__ import annotations


def route(
    rules: list,
    *,
    category: str | None = None,
    field: str | None = None,
    score: float | None = None,
    grounded: bool = True,
    validation_status: str = "passed",
    disagreement: bool = False,
    segmentation_uncertain: bool = False,
    criticality: str | None = None,
) -> str:
    facts = {
        "category": category,
        "field": field,
        "score": score if score is not None else 0.0,
        "grounded": grounded,
        "validation_status": validation_status,
        "disagreement": disagreement,
        "segmentation_uncertain": segmentation_uncertain,
        "criticality": criticality,
    }
    for r in rules or []:
        when = r.when if hasattr(r, "when") else r.get("when", {})
        outcome = r.outcome if hasattr(r, "outcome") else r.get("outcome", "human_review")
        if _matches(when, facts):
            return outcome
    if not grounded or validation_status == "failed" or disagreement or segmentation_uncertain:
        return "human_review"
    return "auto_accept" if (score or 0) >= 0.8 else "human_review"


def _matches(when: dict, facts: dict) -> bool:
    for k, v in (when or {}).items():
        if k == "min_score":
            if facts["score"] < v:
                return False
        elif k == "max_score":
            if facts["score"] > v:
                return False
        elif k == "missing_grounding":
            if bool(v) != (not facts["grounded"]):
                return False
        elif k == "validation_failed":
            if bool(v) != (facts["validation_status"] == "failed"):
                return False
        elif k in ("category", "field", "criticality"):
            vals = v if isinstance(v, list) else [v]
            if facts.get(k) not in vals:
                return False
        elif k in ("disagreement", "segmentation_uncertain") and bool(v) != bool(facts[k]):
            return False
    return True
