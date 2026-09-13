"""§5.3 Unstructured classification via LLM over layout-aware content with
configurable chunking; chunk votes are combined by highest confidence and a
disagreement flag routes to review."""

from __future__ import annotations

from collections import Counter

from docai.exceptions import InvalidModelOutput
from docai.grounding.sources import validate_sources
from docai.layout.chunk import plan_chunks
from docai.layout.preserve import preserve
from docai.schemas.layout import LayoutDocument
from docai.schemas.llm import ClassificationOut

from .base import ClassificationResultData, DocumentResult, WorkflowContext, register
from .routing import route


@register
class ClassifyUnstructured:
    key = "classify_unstructured"

    def process_document(self, ctx: WorkflowContext, layout: LayoutDocument) -> DocumentResult:
        cfg = ctx.config
        result = DocumentResult()
        units = preserve(layout, cfg.layout)
        plan = plan_chunks(
            units,
            cfg.chunking,
            excluded_unit_indexes={
                page.index for page in layout.pages if page.excluded_from_analysis
            },
        )
        result.strategy_used, result.fallback_used = plan.strategy_used, plan.fallback_used
        cat_block = "\n".join(
            f"- {c.key}: {c.name}. {c.description} Evidence: {c.distinguishing_evidence}"
            + (f" Aliases: {', '.join(c.aliases)}." if c.aliases else "")
            for c in cfg.categories
        )
        votes = []
        for ch in plan.chunks:
            call = ctx.call(
                "classification",
                schema=ClassificationOut,
                schema_name="ClassificationOut",
                schema_version=1,
                chunk_index=ch.index,
                fmt={"categories": cat_block, "content": ch.text},
                mock_context={
                    "text": ch.text,
                    "categories": [c.key for c in cfg.categories],
                    "unit_indexes": ch.unit_indexes,
                },
            )
            try:
                res = ctx.invoke(call)
                validate_sources(layout, res.parsed.sources, allowed_indexes=set(ch.unit_indexes))
            except InvalidModelOutput as exc:
                result.warnings.append(f"chunk {ch.index}: invalid model output ({exc.error_code})")
                continue
            result.raw_responses.append(
                {
                    "stage": "classification",
                    "chunk": ch.index,
                    "raw": res.raw_response[:4000],
                    "deployment": res.model_deployment,
                }
            )
            out = res.parsed
            votes.append((out, res.model_deployment, ch.unit_indexes))
        if not votes:
            result.classifications.append(
                ClassificationResultData(
                    category="needs_review", score=0.0, method="llm", review_outcome="human_review"
                )
            )
            return result
        counts = Counter(v[0].category for v in votes)
        best, deployment, urange = max(votes, key=lambda v: v[0].confidence or 0)
        disagreement = len(counts) > 1
        cat = best.category if best.category in {c.key for c in cfg.categories} else "other"
        outcome = route(cfg.routing, category=cat, score=best.confidence, disagreement=disagreement)
        if cat == "other":
            outcome = "human_review"
        result.classifications.append(
            ClassificationResultData(
                category=cat,
                score=best.confidence,
                method="llm",
                llm_evidence=best.evidence,
                sources=[s.model_dump() for s in best.sources],
                model_deployment=deployment,
                prompt=(ctx.prompts["classification"].name, ctx.prompts["classification"].version),
                schema=("ClassificationOut", 1),
                review_outcome=outcome,
                matched_evidence=[
                    {
                        "chunk_votes": dict(counts),
                        "segment_range": [min(urange), max(urange)] if urange else None,
                    }
                ],
            )
        )
        return result
