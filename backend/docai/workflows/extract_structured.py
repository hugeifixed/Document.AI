"""§5.4 Structured extraction: Layout → generic (non-LLM) layout preservation →
generic LLM extractor in DEFAULT mode (all key/value pairs, GenericKVOut) or
CUSTOM mode (Pydantic schema fields via the shared extraction core)."""
from __future__ import annotations

from docai.exceptions import InvalidModelOutput
from docai.layout.chunk import plan_chunks
from docai.layout.preserve import preserve
from docai.schemas.layout import LayoutDocument
from docai.schemas.llm import GenericKVOut
from docai.validation.normalize import normalize_value

from .base import DocumentResult, FieldResultData, WorkflowContext, register
from .extraction_core import ground
from .routing import route


@register
class ExtractStructured:
    key = "extract_structured"

    def process_document(self, ctx: WorkflowContext, layout: LayoutDocument) -> DocumentResult:
        cfg = ctx.config
        if cfg.mode == "custom":
            from .extraction_core import run_extraction
            return run_extraction(ctx, layout, cfg.schema_, document_type=cfg.document_type)
        result = DocumentResult()
        units = preserve(layout, cfg.layout)
        plan = plan_chunks(units, cfg.chunking)
        result.strategy_used, result.fallback_used = plan.strategy_used, plan.fallback_used
        seen = set()
        for ch in plan.chunks:
            call = ctx.call("generic_kv", schema=GenericKVOut, schema_name="GenericKVOut", schema_version=1,
                            fmt={"content": ch.text}, mock_context={"text": ch.text})
            try:
                res = ctx.llm.invoke(call)
            except InvalidModelOutput as exc:
                result.warnings.append(f"chunk {ch.index}: invalid model output ({exc.error_code})"); continue
            result.raw_responses.append({"stage": "generic_kv", "chunk": ch.index, "raw": res.raw_response[:4000],
                                         "deployment": res.model_deployment})
            for p in res.parsed.pairs:
                key = p.name.strip()
                if key.lower() in seen:
                    continue
                seen.add(key.lower())
                ui = ch.unit_indexes[min(p.unit_index or 0, len(ch.unit_indexes) - 1)] if ch.unit_indexes else 0
                g = ground(layout, p.model_copy(update={"unit_index": ui}), ui)
                result.fields.append(FieldResultData(
                    name=key, field_type="string", raw_value=p.value, normalized_value=normalize_value(p.value),
                    score=p.confidence, source_text=p.evidence, method="llm", strategy=plan.strategy_used,
                    fallback_used=plan.fallback_used or "", model_deployment=res.model_deployment,
                    prompt=(ctx.prompts["generic_kv"].name, ctx.prompts["generic_kv"].version),
                    schema=("GenericKVOut", 1), api_version=ctx.api_version, validation_status="not_run",
                    validation_messages=[], suggested_correction=None, grounding=g,
                    review_outcome=route(cfg.routing, field=key, score=p.confidence, grounded=g is not None)))
        return result
