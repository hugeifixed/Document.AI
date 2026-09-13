"""§5.1 Unbundling → classification → extraction. Segments are proposed by the
LLM (page snippets, or per-chunk for long files), validated hard (ordered,
non-overlapping, full coverage) with a whole-file fallback that can never lose
pages, then each segment is routed to its category's extraction schema."""

from __future__ import annotations

from typing import Any, TypedDict

from docai.exceptions import InvalidModelOutput
from docai.grounding.sources import validate_sources
from docai.layout.preserve import preserve
from docai.schemas.layout import LayoutDocument
from docai.schemas.llm import SegmentationOut

from .base import ClassificationResultData, DocumentResult, SegmentResult, WorkflowContext, register
from .extraction_core import run_extraction
from .routing import route

SNIPPET_CHARS = 500


class NormalizedSegment(TypedDict):
    start: int
    end: int
    category: str
    confidence: float | None
    evidence: str
    continuation_of: int | None
    sources: list[dict[str, Any]]


def validate_segments(raw: list[dict[str, Any]], n_units: int) -> list[NormalizedSegment] | None:
    try:
        segs: list[NormalizedSegment] = []
        for proposed in raw:
            raw_confidence = proposed.get("confidence")
            raw_continuation = proposed.get("continuation_of")
            raw_sources = proposed.get("sources", [])
            if not isinstance(raw_sources, list):
                return None
            sources: list[dict[str, Any]] = []
            for source in raw_sources:
                if not isinstance(source, dict):
                    return None
                sources.append({str(key): value for key, value in source.items()})
            segs.append(
                {
                    "start": int(proposed["start_unit"]),
                    "end": int(proposed["end_unit"]),
                    "category": str(proposed.get("category") or "other"),
                    "confidence": (float(raw_confidence) if raw_confidence is not None else None),
                    "evidence": str(proposed.get("evidence") or ""),
                    "continuation_of": (
                        int(raw_continuation) if raw_continuation is not None else None
                    ),
                    "sources": sources,
                }
            )
    except (KeyError, TypeError, ValueError):
        return None
    if not segs:
        return None
    segs.sort(key=lambda s: (s["start"], s["end"]))
    fixed: list[NormalizedSegment] = []
    for s in segs:
        a = max(0, min(s["start"], n_units - 1))
        b = max(a, min(s["end"], n_units - 1))
        if not fixed:
            a = 0
        else:
            prev = fixed[-1]
            if a <= prev["end"]:
                a = prev["end"] + 1
                if a > b:
                    continue
            elif a > prev["end"] + 1:
                prev["end"] = a - 1
        fixed.append({**s, "start": a, "end": b})
    if not fixed:
        return None
    fixed[-1]["end"] = n_units - 1
    return fixed


@register
class UnbundleClassifyExtract:
    key = "unbundle_classify_extract"

    def process_document(self, ctx: WorkflowContext, layout: LayoutDocument) -> DocumentResult:
        cfg = ctx.config
        result = DocumentResult()
        unit_texts = preserve(layout, cfg.layout)
        n = len(unit_texts)
        cats = {c.key: c for c in cfg.categories}
        cat_block = "\n".join(
            f"- {c.key}: {c.name}. {c.description} Evidence: {c.distinguishing_evidence}"
            + (f" Aliases: {', '.join(c.aliases)}." if c.aliases else "")
            + (
                f" Continuation pages: {c.continuation_characteristics}"
                if c.continuation_characteristics
                else ""
            )
            for c in cfg.categories
        )
        whole: list[NormalizedSegment] = [
            {
                "start": 0,
                "end": max(n - 1, 0),
                "category": "other",
                "confidence": None,
                "evidence": "",
                "continuation_of": None,
                "sources": [],
            }
        ]

        segs: list[NormalizedSegment]
        if n == 0:
            segs = whole
        else:
            excluded = {page.index for page in layout.pages if page.excluded_from_analysis}
            snippets = "\n".join(
                f"[{i}] {' '.join(t.split())[:SNIPPET_CHARS]}"
                for i, t in enumerate(unit_texts)
                if i not in excluded
            )
            call = ctx.call(
                "segmentation",
                schema=SegmentationOut,
                schema_name="SegmentationOut",
                schema_version=1,
                fmt={"categories": cat_block, "units": snippets},
                mock_context={
                    "unit_texts": unit_texts,
                    "categories": list(cats),
                    "excluded_unit_indexes": excluded,
                },
            )
            try:
                res = ctx.invoke(call)
                for segment in res.parsed.segments:
                    validate_sources(
                        layout,
                        segment.sources,
                        allowed_indexes=set(range(segment.start_unit, segment.end_unit + 1)),
                    )
                result.raw_responses.append(
                    {
                        "stage": "segmentation",
                        "raw": res.raw_response[:4000],
                        "deployment": res.model_deployment,
                        "latency_ms": res.latency_ms,
                    }
                )
                segs = validate_segments([s.model_dump() for s in res.parsed.segments], n) or whole
                if segs is whole:
                    result.warnings.append(
                        "segmentation proposal unusable; whole-file fallback applied"
                    )
            except InvalidModelOutput as exc:
                result.warnings.append(
                    f"segmentation: invalid model output ({exc.error_code}); whole-file fallback"
                )
                segs = whole

        for i, s in enumerate(segs):
            cat = s["category"] if s["category"] in cats else "other"
            uncertain = (s.get("confidence") or 0) < 0.5 or cat == "other"
            outcome = route(
                cfg.routing,
                category=cat,
                score=s.get("confidence"),
                segmentation_uncertain=uncertain,
            )
            if cat == "other" and cfg.other_behavior == "needs_review":
                outcome = "human_review"
            result.segments.append(
                SegmentResult(
                    index=i,
                    start_unit=s["start"],
                    end_unit=s["end"],
                    category=cat,
                    score=s.get("confidence"),
                    method="segmentation",
                    evidence={"text": s.get("evidence", ""), "review": outcome},
                    continuation_of=s.get("continuation_of"),
                    sources=s.get("sources", []),
                )
            )
            result.classifications.append(
                ClassificationResultData(
                    category=cat,
                    score=s.get("confidence"),
                    method="segmentation",
                    llm_evidence=s.get("evidence", ""),
                    sources=s.get("sources", []),
                    prompt=(ctx.prompts["segmentation"].name, ctx.prompts["segmentation"].version),
                    schema=("SegmentationOut", 1),
                    segment_index=i,
                    review_outcome=outcome,
                )
            )
            schema_name = cats[cat].extraction_schema if cat in cats else None
            schema = (
                next((sc for sc in cfg.schemas if sc.name == schema_name), None)
                if schema_name
                else None
            )
            if schema:
                run_extraction(
                    ctx,
                    layout,
                    schema,
                    document_type=cat,
                    unit_range=(s["start"], s["end"]),
                    reconciliation_policy=cfg.reconciliation.policy,
                    segment_index=i,
                    result=result,
                )
        return result
