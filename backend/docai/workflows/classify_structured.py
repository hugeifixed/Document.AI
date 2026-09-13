"""§5.2 Structured classification: deterministic rules (regex-safety-checked)
with scoring, groups and exclusions, optional LLM fallback, and honest
routing of ambiguous/unmatched/below-threshold results to other/needs_review."""

from __future__ import annotations

import hashlib
import json
import re

from docai.exceptions import InvalidModelOutput
from docai.grounding.sources import validate_sources
from docai.layout.preserve import preserve
from docai.schemas.config import RulePattern
from docai.schemas.layout import LayoutDocument
from docai.schemas.llm import ClassificationOut
from docai.validation.regex_safety import validate_regex

from .base import ClassificationResultData, DocumentResult, WorkflowContext, register
from .routing import route


def _find(p: RulePattern, text: str, layout: LayoutDocument) -> dict | None:
    flags = 0 if p.case_sensitive else re.I
    if p.kind == "regex":
        rx = validate_regex(p.pattern)
        m = rx.search(text)
    elif p.kind == "exact_title":
        m = re.search(r"^\s*" + re.escape(p.pattern) + r"\s*$", text, flags | re.M)
    elif p.kind == "form_id":
        m = re.search(r"\b" + re.escape(p.pattern) + r"\b", text, flags)
    elif p.kind == "identifier_format":
        rx = validate_regex(p.pattern)
        m = rx.search(text)
    else:  # phrase
        m = re.search(re.escape(p.pattern), text, flags)
    if not m:
        return None
    # locate unit + line for evidence
    pos = m.start()
    unit = text[:pos].count("\f")
    return {
        "pattern": p.pattern,
        "kind": p.kind,
        "weight": p.weight,
        "group": p.group,
        "match": m.group(0)[:120],
        "unit_index": unit,
    }


def score_rules(rule_sets, text: str, layout: LayoutDocument) -> list[dict]:
    scored = []
    for rs in rule_sets:
        matched, excluded = [], []
        for p in rs.exclusions:
            hit = _find(p, text, layout)
            if hit:
                excluded.append(hit)
        if excluded:
            scored.append(
                {
                    "category": rs.category,
                    "score": 0.0,
                    "matched": [],
                    "excluded": excluded,
                    "eligible": False,
                }
            )
            continue
        req_ok = True
        groups_hit = set()
        for p in rs.required:
            hit = _find(p, text, layout)
            if hit:
                matched.append(hit)
                groups_hit.add(p.group)
            elif p.group is None:
                req_ok = False
        req_groups = {p.group for p in rs.required if p.group}
        if req_groups - groups_hit:
            req_ok = False
        for p in rs.optional:
            hit = _find(p, text, layout)
            if hit:
                matched.append(hit)
        score = sum(h["weight"] for h in matched) if req_ok else 0.0
        scored.append(
            {
                "category": rs.category,
                "score": score,
                "matched": matched,
                "excluded": [],
                "eligible": req_ok and score >= rs.threshold,
                "threshold": rs.threshold,
                "version": rs.version,
            }
        )
    return scored


@register
class ClassifyStructured:
    key = "classify_structured"

    def process_document(self, ctx: WorkflowContext, layout: LayoutDocument) -> DocumentResult:
        cfg = ctx.config
        result = DocumentResult()
        text = "\f".join(preserve(layout, cfg.layout))
        scored = score_rules(cfg.rules, text, layout)
        rule_version = hashlib.sha256(
            json.dumps([r.model_dump() for r in cfg.rules], sort_keys=True).encode()
        ).hexdigest()[:12]
        eligible = sorted([s for s in scored if s["eligible"]], key=lambda s: -s["score"])
        category, score, method, evidence_llm, sources = "other", 0.0, "rules", "", []
        ambiguous = (
            len(eligible) >= 2
            and (eligible[0]["score"] - eligible[1]["score"]) < cfg.ambiguity_margin
        )
        if eligible and not ambiguous:
            category, score = eligible[0]["category"], eligible[0]["score"]
        elif cfg.use_llm_fallback:
            cats = [r.category for r in cfg.rules] + [c.key for c in cfg.categories]
            call = ctx.call(
                "classification",
                schema=ClassificationOut,
                schema_name="ClassificationOut",
                schema_version=1,
                fmt={
                    "categories": "\n".join(f"- {c}" for c in dict.fromkeys(cats)),
                    "content": text[:60000],
                },
                mock_context={"text": text, "categories": list(dict.fromkeys(cats))},
            )
            try:
                res = ctx.invoke(call)
                validate_sources(layout, res.parsed.sources)
                result.raw_responses.append(
                    {
                        "stage": "classification",
                        "raw": res.raw_response[:4000],
                        "deployment": res.model_deployment,
                    }
                )
                category, score, method = res.parsed.category, res.parsed.confidence or 0.0, "llm"
                evidence_llm, sources = (
                    res.parsed.evidence,
                    [s.model_dump() for s in res.parsed.sources],
                )
            except InvalidModelOutput as exc:
                result.warnings.append(f"llm fallback invalid output ({exc.error_code})")
        if ambiguous or (category == "other"):
            category = "needs_review" if ambiguous else "other"
        best = (
            eligible[0] if eligible else (max(scored, key=lambda s: s["score"]) if scored else None)
        )
        outcome = route(
            cfg.routing,
            category=category,
            score=min(score / max(best["threshold"], 1e-9), 1.0)
            if best and best.get("threshold")
            else score,
            disagreement=ambiguous,
        )
        if category in ("other", "needs_review"):
            outcome = "human_review"
        result.classifications.append(
            ClassificationResultData(
                category=category,
                score=score,
                method=method,
                rule_score=best["score"] if best else None,
                matched_evidence=best["matched"] if best else [],
                excluded_evidence=[e for s in scored for e in s["excluded"]],
                llm_evidence=evidence_llm,
                sources=sources
                or (
                    [
                        {"unit_index": h["unit_index"], "quote": h["match"]}
                        for h in (best["matched"] if best else [])
                    ]
                ),
                rule_version=rule_version,
                review_outcome=outcome,
                prompt=(ctx.prompts["classification"].name, ctx.prompts["classification"].version)
                if method == "llm"
                else None,
                schema=("ClassificationOut", 1) if method == "llm" else None,
            )
        )
        return result
