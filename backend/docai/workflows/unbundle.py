"""Identify bounded document instances before independently extracting their fields."""

from __future__ import annotations

from docai.layout.preserve import preserve
from docai.schemas.layout import LayoutDocument

from .base import ClassificationResultData, DocumentResult, SegmentResult, WorkflowContext, register
from .extraction_core import run_extraction
from .routing import route
from .segmentation import identify_documents


@register
class UnbundleClassifyExtract:
    key = "unbundle_classify_extract"

    def process_document(self, ctx: WorkflowContext, layout: LayoutDocument) -> DocumentResult:
        cfg = ctx.config
        result = DocumentResult()
        unit_texts = preserve(layout, cfg.layout)
        cats = {c.key: c for c in cfg.categories}
        segs = identify_documents(ctx, layout, unit_texts, result)

        for i, s in enumerate(segs):
            cat = s.category if s.category in cats else "other"
            uncertain = (s.confidence or 0) < 0.5 or cat == "other"
            outcome = route(
                cfg.routing,
                category=cat,
                score=s.confidence,
                segmentation_uncertain=uncertain,
            )
            if cat == "other" and cfg.other_behavior == "needs_review":
                outcome = "human_review"
            if s.review_reasons:
                outcome = "human_review"
                result.warnings.append(
                    f"document {i + 1}, pages {s.start + 1}–{s.end + 1}: "
                    + ", ".join(s.review_reasons)
                )
            result.segments.append(
                SegmentResult(
                    index=i,
                    start_unit=s.start,
                    end_unit=s.end,
                    category=cat,
                    score=s.confidence,
                    method="segmentation",
                    evidence={
                        "text": s.evidence,
                        "review": outcome,
                        "review_reasons": s.review_reasons,
                        "boundary": s.boundary,
                    },
                    continuation_of=None,
                    sources=s.sources,
                )
            )
            result.classifications.append(
                ClassificationResultData(
                    category=cat,
                    score=s.confidence,
                    method="segmentation",
                    llm_evidence=s.evidence,
                    sources=s.sources,
                    prompt=(ctx.prompts["segmentation"].name, ctx.prompts["segmentation"].version),
                    schema=("SegmentationOut", 2),
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
                first_field = len(result.fields)
                run_extraction(
                    ctx,
                    layout,
                    schema,
                    document_type=cat,
                    unit_range=(s.start, s.end),
                    reconciliation_policy=cfg.reconciliation.policy,
                    segment_index=i,
                    segment_total=len(segs),
                    result=result,
                    unit_texts=unit_texts,
                )
                if s.review_reasons:
                    for extracted in result.fields[first_field:]:
                        extracted.review_outcome = "human_review"
                        extracted.validation_messages.extend(s.review_reasons)
        return result
