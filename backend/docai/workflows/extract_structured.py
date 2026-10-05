"""§5.4 Structured extraction: Layout → generic (non-LLM) layout preservation →
generic LLM extractor in DEFAULT mode (all key/value pairs, GenericKVOut) or
CUSTOM mode (Pydantic schema fields via the shared extraction core)."""

from __future__ import annotations

import json

from loguru import logger

from docai.exceptions import InvalidModelOutput
from docai.grounding.sources import submitted_sources
from docai.layout.chunk import plan_chunks
from docai.layout.preserve import preserve
from docai.schemas.layout import LayoutDocument
from docai.schemas.llm import GenericKVOut
from docai.validation.normalize import normalize_value

from .auto_occurrences import AutoOccurrences
from .base import DocumentResult, FieldResultData, WorkflowContext, register
from .citation_repair import CitationRepairer
from .evidence import ExtractionEvidence


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
        prompt = ctx.call("generic_kv", schema=GenericKVOut, fmt={"content": ""})
        prompt_overhead = (
            len(prompt.system)
            + len(prompt.user)
            + len(json.dumps(GenericKVOut.model_json_schema()))
        )
        plan = plan_chunks(
            units,
            cfg.chunking,
            unit_kind="sheet" if layout.sheets else "page",
            prompt_overhead_chars=prompt_overhead,
            excluded_unit_indexes={
                page.index for page in layout.pages if page.excluded_from_analysis
            },
        )
        result.strategy_used, result.fallback_used = plan.strategy_used, plan.fallback_used
        occurrences = AutoOccurrences(layout)
        repairer = CitationRepairer(ctx, layout)
        total_chunks = len(plan.chunks)
        result.extraction_chunks += total_chunks
        for position, ch in enumerate(plan.chunks):
            ctx.report_progress(
                "analyzing", "extracting", completed=position, total=total_chunks, unit="chunks"
            )
            call = ctx.call(
                "generic_kv",
                schema=GenericKVOut,
                schema_name="GenericKVOut",
                schema_version=1,
                chunk_index=ch.index,
                fmt={"content": ch.text},
                mock_context={"text": ch.text, "unit_indexes": ch.unit_indexes},
            )
            try:
                res = ctx.invoke(call)
                ctx.report_progress(
                    "analyzing",
                    "checking_evidence",
                    completed=position,
                    total=total_chunks,
                    unit="chunks",
                )
            except InvalidModelOutput as exc:
                ctx.discard_checkpoint(call)
                result.rejected_extraction_chunks += 1
                logger.bind(
                    event="extraction_chunk_invalid",
                    stage="generic_kv",
                    chunk_index=ch.index,
                    error_code=exc.error_code,
                    **exc.diagnostics,
                ).warning("Extraction chunk was rejected")
                result.warnings.append(f"chunk {ch.index}: invalid model output ({exc.error_code})")
                ctx.report_progress(
                    "analyzing",
                    "extracting",
                    completed=position + 1,
                    total=total_chunks,
                    unit="chunks",
                    force=position + 1 == total_chunks,
                )
                continue
            result.raw_responses.append(
                {
                    "stage": "generic_kv",
                    "chunk": ch.index,
                    "raw": res.raw_response[:4000],
                    "deployment": res.model_deployment,
                }
            )
            evidence = ExtractionEvidence(ctx, layout, scalar_indexes=set(ch.unit_indexes))
            res.parsed.pairs = repairer.repair(
                call, res.parsed.pairs, {}, set(ch.unit_indexes), result
            )
            invalid_count = evidence.inspect_chunk(
                res.parsed.pairs,
                set(ch.unit_indexes),
                call,
                res,
                repaired_ids=repairer.repaired_ids,
                repaired_properties=repairer.repaired_properties,
            )
            if invalid_count:
                result.warnings.append(
                    f"chunk {ch.index}: {invalid_count} fields need evidence review (INVALID_SOURCE_REFERENCE)"
                )
            submitted_layout, _allowed_ids = submitted_sources(
                layout, ch.text, set(ch.unit_indexes)
            )
            for p in res.parsed.pairs:
                key = p.name.strip()
                decision = evidence.decide(p.model_copy(update={"name": key}), selected_candidate=p)
                if occurrences.is_repeat(p, decision, set(ch.unit_indexes), submitted_layout):
                    continue
                result.fields.append(
                    FieldResultData(
                        name=key,
                        field_type="string",
                        raw_value=p.value,
                        normalized_value=normalize_value(p.value),
                        score=p.confidence,
                        source_text=p.evidence,
                        method="llm",
                        strategy=plan.strategy_used,
                        fallback_used=plan.fallback_used or "",
                        model_deployment=res.model_deployment,
                        prompt=(ctx.prompts["generic_kv"].name, ctx.prompts["generic_kv"].version),
                        schema=("GenericKVOut", 1),
                        api_version=ctx.api_version,
                        validation_status=decision.validation.status,
                        validation_messages=decision.validation.messages,
                        suggested_correction=None,
                        grounding=decision.grounding,
                        review_outcome=decision.review_outcome,
                    )
                )
            ctx.report_progress(
                "analyzing",
                "extracting",
                completed=position + 1,
                total=total_chunks,
                unit="chunks",
                force=position + 1 == total_chunks,
            )
        return result
