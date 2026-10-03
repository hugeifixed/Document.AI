"""Shared extraction pipeline used by every extraction-capable strategy:
preserved text → chunk plan → LLM per chunk (Pydantic ExtractionOut) →
reconcile → ground → validate → route. Invalid model output is caught per
chunk and recorded; rejected citations are isolated to individual fields."""

from __future__ import annotations

import json

from loguru import logger

from docai.exceptions import InvalidModelOutput
from docai.layout.chunk import plan_chunks
from docai.layout.preserve import preserve
from docai.layout.reconcile import reconcile
from docai.schemas.config import ExtractionSchemaConfig, FieldSpec
from docai.schemas.layout import LayoutDocument
from docai.schemas.llm import ExtractionOut, FieldOut
from docai.validation.normalize import normalize_value
from docai.validation.rules import validate_field

from .base import DocumentResult, FieldResultData, WorkflowContext
from .citation_repair import CitationRepairer
from .evidence import ExtractionEvidence


def fields_block(fields: list[FieldSpec], guidance: dict | None = None) -> str:
    lines = []
    for f in fields:
        extra = []
        if f.type != "string":
            extra.append(f"type={f.type}")
        if f.type == "list":
            extra.append(
                "value must be a JSON array encoded as a string; preserve row associations, duplicates and leading zeros; use null when absent; return property_sources for every non-null leaf using JSON Pointer paths such as /0/name and exact source IDs for that specific row. A rendered visual row may group several line IDs at its end: these identify separate original lines, so cite all supporting IDs in that row if unsure which contains the value; the first ID does not cover the entire row"
            )
        if f.required:
            extra.append("required")
        if f.enum:
            extra.append("one of: " + ", ".join(f.enum))
        g = (guidance or {}).get(f.name) or f.guidance
        line = (
            f'- "{f.name}"'
            + (f" — {f.description}" if f.description else "")
            + (f" ({'; '.join(extra)})" if extra else "")
        )
        if g:
            line += f"\n  guidance: {g}"
        lines.append(line)
    return "\n".join(lines)


def run_extraction(
    ctx: WorkflowContext,
    layout: LayoutDocument,
    schema: ExtractionSchemaConfig,
    *,
    document_type: str | None,
    unit_range: tuple[int, int] | None = None,
    guidance: dict | None = None,
    reconciliation_policy: str = "highest_score",
    segment_index: int | None = None,
    segment_total: int | None = None,
    result: DocumentResult | None = None,
    unit_texts: list[str] | None = None,
) -> DocumentResult:
    result = result or DocumentResult()
    cfg = ctx.config
    unit_texts = preserve(layout, cfg.layout) if unit_texts is None else unit_texts
    fblock = fields_block(schema.fields, guidance)
    prompt = ctx.call(
        "extraction",
        schema=ExtractionOut,
        fmt={
            "document_type": document_type or "unknown",
            "fields": fblock,
            "content": "",
        },
    )
    prompt_overhead = (
        len(prompt.system) + len(prompt.user) + len(json.dumps(ExtractionOut.model_json_schema()))
    )
    lo, hi = unit_range if unit_range else (0, len(unit_texts) - 1)
    sub_texts = unit_texts[lo : hi + 1]
    unit_kind = "sheet" if layout.sheets else "page"
    plan = plan_chunks(
        sub_texts,
        cfg.chunking,
        unit_kind=unit_kind,
        prompt_overhead_chars=prompt_overhead,
        excluded_unit_indexes={
            page.index - lo for page in layout.pages if page.excluded_from_analysis
        },
    )
    result.strategy_used = plan.strategy_used
    result.fallback_used = plan.fallback_used
    if plan.fallback_used:
        result.warnings.append(f"chunking fallback: {plan.fallback_used}")

    per_chunk: list[list[FieldOut]] = []
    candidate_chunks: dict[int, int] = {}
    evidence = ExtractionEvidence(ctx, layout, scalar_indexes=set(range(lo, hi + 1)))
    repairer = CitationRepairer(ctx, layout)
    field_types = {spec.name: spec.type for spec in schema.fields}
    total_chunks = len(plan.chunks)
    result.extraction_chunks += total_chunks
    segment_kwargs = (
        {"segment_current": segment_index + 1, "segment_total": segment_total}
        if segment_index is not None and segment_total is not None
        else {}
    )
    for position, ch in enumerate(plan.chunks):
        ctx.report_progress(
            "analyzing",
            "extracting",
            completed=position,
            total=total_chunks,
            unit="chunks",
            **segment_kwargs,
        )
        call = ctx.call(
            "extraction",
            schema=ExtractionOut,
            schema_name=schema.name,
            schema_version=schema.version,
            chunk_index=ch.index,
            segment_index=segment_index,
            fmt={"document_type": document_type or "unknown", "fields": fblock, "content": ch.text},
            mock_context={
                "text": ch.text,
                "fields": [f.model_dump() for f in schema.fields],
                "unit_indexes": [index + lo for index in ch.unit_indexes],
            },
        )
        try:
            res = ctx.invoke(call)
            ctx.report_progress(
                "analyzing",
                "checking_evidence",
                completed=position,
                total=total_chunks,
                unit="chunks",
                **segment_kwargs,
            )
        except InvalidModelOutput as exc:
            ctx.discard_checkpoint(call)
            result.rejected_extraction_chunks += 1
            logger.bind(
                event="extraction_chunk_invalid",
                stage="extraction",
                chunk_index=ch.index,
                segment_index=segment_index,
                error_code=exc.error_code,
                **exc.diagnostics,
            ).warning("Extraction chunk requires review")
            result.warnings.append(
                f"chunk {ch.index}: invalid model output rejected ({exc.error_code})"
            )
            result.raw_responses.append(
                {
                    "stage": "extraction",
                    "chunk": ch.index,
                    "error": exc.error_code,
                    "diagnostics": exc.diagnostics,
                }
            )
            ctx.report_progress(
                "analyzing",
                "extracting",
                completed=position + 1,
                total=total_chunks,
                unit="chunks",
                force=position + 1 == total_chunks,
                **segment_kwargs,
            )
            continue
        result.raw_responses.append(
            {
                "stage": "extraction",
                "chunk": ch.index,
                "raw": res.raw_response[:4000],
                "deployment": res.model_deployment,
                "latency_ms": res.latency_ms,
            }
        )
        out: ExtractionOut = res.parsed
        out.fields = repairer.repair(
            call, out.fields, field_types, {index + lo for index in ch.unit_indexes}, result
        )
        invalid_count = evidence.inspect_chunk(
            out.fields,
            {index + lo for index in ch.unit_indexes},
            call,
            res,
            repaired_ids=repairer.repaired_ids,
            repaired_properties=repairer.repaired_properties,
        )
        if invalid_count:
            result.warnings.append(
                f"chunk {ch.index}: {invalid_count} fields need evidence review (INVALID_SOURCE_REFERENCE)"
            )
        per_chunk.append(out.fields)
        candidate_chunks.update({id(candidate): ch.index for candidate in out.fields})
        deployment = res.model_deployment
        ctx.report_progress(
            "analyzing",
            "extracting",
            completed=position + 1,
            total=total_chunks,
            unit="chunks",
            force=position + 1 == total_chunks,
            **segment_kwargs,
        )
    if not per_chunk:
        return result

    ctx.report_progress("analyzing", "checking_evidence", **segment_kwargs)
    merged = reconcile(
        per_chunk, reconciliation_policy, {spec.name: spec.type for spec in schema.fields}
    )
    values = {name: rf.field.value for name, rf in merged.items()}
    for spec in schema.fields:
        rf = merged.get(spec.name)
        fo = rf.field if rf else FieldOut(name=spec.name, value=None, confidence=0.0)
        vo = validate_field(
            spec.name,
            fo.value,
            spec.validation + ([{"kind": "required"}] if spec.required else []),
            values,
            spec.type,
        )
        if fo.value not in (None, "") and spec.enum and str(fo.value) not in spec.enum:
            vo.messages.append(f"{spec.name} must be one of {spec.enum}")
            vo.status = "failed"
        decision = evidence.decide(
            fo,
            selected_candidate=rf.selected_candidate if rf else None,
            field_type=spec.type,
            validation=vo,
            conflict=bool(rf and rf.conflict),
        )
        result.fields.append(
            FieldResultData(
                name=spec.name,
                field_type=spec.type,
                raw_value=fo.value,
                normalized_value=normalize_value(fo.value, spec.type)
                if fo.value not in (None, "")
                else None,
                score=fo.confidence,
                source_text=fo.evidence,
                method="llm",
                strategy=plan.strategy_used,
                fallback_used=plan.fallback_used or "",
                model_deployment=deployment or "",
                prompt=(ctx.prompts["extraction"].name, ctx.prompts["extraction"].version),
                schema=(schema.name, schema.version),
                api_version=ctx.api_version,
                validation_status=decision.validation.status,
                validation_messages=decision.validation.messages,
                suggested_correction=decision.validation.suggested_correction,
                grounding=decision.grounding,
                review_outcome=decision.review_outcome,
                segment_index=segment_index,
                candidates=[
                    {
                        **c.model_dump(),
                        "chunk_index": candidate_chunks[id(c)],
                        "segment_index": segment_index,
                    }
                    for c in (rf.candidates if rf else [])
                ],
                conflict=bool(rf and rf.conflict),
                property_evidence=decision.property_evidence,
            )
        )
    return result
