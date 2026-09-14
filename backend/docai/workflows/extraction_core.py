"""Shared extraction pipeline used by every extraction-capable strategy:
preserved text → chunk plan → LLM per chunk (Pydantic ExtractionOut) →
reconcile → ground → validate → route. Invalid model output is caught per
chunk and recorded; rejected citations are isolated to individual fields."""

from __future__ import annotations

from loguru import logger

from docai.exceptions import InvalidModelOutput
from docai.grounding.locate import locate_in_page, locate_in_sheet
from docai.grounding.selection_marks import ground_selection_mark
from docai.grounding.sources import cited_unit, source_elements, validate_sources
from docai.layout.chunk import plan_chunks
from docai.layout.preserve import preserve
from docai.layout.reconcile import reconcile
from docai.schemas.config import ExtractionSchemaConfig, FieldSpec
from docai.schemas.layout import LayoutDocument, LayoutPage
from docai.schemas.llm import ExtractionOut, FieldOut
from docai.validation.collections import LIST_CONFLICT, LIST_REVIEW
from docai.validation.normalize import normalize_value
from docai.validation.rules import validate_field

from .base import DocumentResult, FieldResultData, WorkflowContext
from .routing import route


def fields_block(fields: list[FieldSpec], guidance: dict | None = None) -> str:
    lines = []
    for f in fields:
        extra = []
        if f.type != "string":
            extra.append(f"type={f.type}")
        if f.type == "list":
            extra.append(
                "value must be a JSON array encoded as a string; preserve row associations, duplicates and leading zeros; use null when absent"
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


def ground(
    layout: LayoutDocument,
    f: FieldOut,
    unit_hint: int | None,
    *,
    allowed_indexes: set[int] | None = None,
) -> dict | None:
    if f.value in (None, ""):
        return None
    try:
        validate_sources(layout, f.sources, unit_index=unit_hint, allowed_indexes=allowed_indexes)
    except InvalidModelOutput:
        return None
    claimed, hit = ground_selection_mark(layout, f, unit_hint, allowed_indexes=allowed_indexes)
    if claimed:
        return hit
    units = {
        unit.index: unit
        for unit in layout.units
        if not (isinstance(unit, LayoutPage) and unit.excluded_from_analysis)
        and (allowed_indexes is None or unit.index in allowed_indexes)
    }
    # Explicit citations bound the search. Never substitute another occurrence of
    # a repeated value on an uncited page, or outside this extraction segment.
    order = list(dict.fromkeys(source.unit_index for source in f.sources))
    if unit_hint is not None:
        order = [unit_hint] + [index for index in order if index != unit_hint]
    for index in order or list(units):
        ids = {
            source_id
            for source in f.sources
            if source.unit_index == index
            for source_id in source.ids
        }
        unit = cited_unit(units[index], ids)
        hit = (
            locate_in_page(f.value, unit, f.evidence)
            if isinstance(unit, LayoutPage)
            else locate_in_sheet(f.value, unit)
        )
        if hit:
            return {"unit_index": index, **hit}
    return None


EVIDENCE_REVIEW_MESSAGE = "The model cited an unavailable document location. Verify this value against the original document."


def check_field_sources(ctx, layout, fields, allowed_indexes, call, response) -> set[int]:
    """Reject evidence per candidate, without discarding independently valid values."""
    invalid = set()
    issues = []
    for index, candidate in enumerate(fields):
        try:
            validate_sources(
                layout,
                candidate.sources,
                unit_index=candidate.unit_index,
                allowed_indexes=allowed_indexes,
            )
        except InvalidModelOutput as exc:
            invalid.add(id(candidate))
            issues.append({"field_index": index, **exc.diagnostics})
    if issues:
        logger.bind(
            event="extraction_evidence_invalid",
            stage=call.stage,
            chunk_index=call.chunk_index,
            segment_index=call.segment_index,
            invalid_fields=len(issues),
            validation_reasons=sorted({issue["validation_reason"] for issue in issues}),
            total_fields=len(fields),
        ).warning("Fields with invalid evidence require review")
        if ctx.debug_capture is not None:
            try:
                ctx.debug_capture(
                    {
                        "stage": call.stage,
                        "chunk_index": call.chunk_index,
                        "segment_index": call.segment_index,
                        "issues": issues,
                        "prompt_name": call.prompt_name,
                        "prompt_version": call.prompt_version,
                        "deployment": response.model_deployment,
                        "submitted_content": call.user,
                        "parsed_response": response.parsed.model_dump(mode="json"),
                        "raw_response": response.raw_response,
                        "allowed_source_ids": {
                            str(unit.index): sorted(source_elements(unit))
                            for unit in layout.units
                            if unit.index in allowed_indexes
                        },
                    }
                )
            except Exception as exc:  # noqa: BLE001 -- diagnostics must not affect processing
                logger.bind(
                    event="llm_debug_capture_failed", error_type=type(exc).__name__
                ).warning("Local LLM debug capture failed")
    return invalid


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
) -> DocumentResult:
    result = result or DocumentResult()
    cfg = ctx.config
    unit_texts = preserve(layout, cfg.layout)
    lo, hi = unit_range if unit_range else (0, len(unit_texts) - 1)
    sub_texts = unit_texts[lo : hi + 1]
    unit_kind = "sheet" if layout.sheets else "page"
    plan = plan_chunks(
        sub_texts,
        cfg.chunking,
        unit_kind=unit_kind,
        excluded_unit_indexes={
            page.index - lo for page in layout.pages if page.excluded_from_analysis
        },
    )
    result.strategy_used = plan.strategy_used
    result.fallback_used = plan.fallback_used
    if plan.fallback_used:
        result.warnings.append(f"chunking fallback: {plan.fallback_used}")

    per_chunk: list[list[FieldOut]] = []
    checkbox_grounding: dict[int, tuple[bool, dict | None]] = {}
    fblock = fields_block(schema.fields, guidance)
    total_chunks = len(plan.chunks)
    result.extraction_chunks += total_chunks
    invalid_evidence: set[int] = set()
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
        invalid = check_field_sources(
            ctx, layout, out.fields, {index + lo for index in ch.unit_indexes}, call, res
        )
        invalid_evidence.update(invalid)
        if invalid:
            result.warnings.append(
                f"chunk {ch.index}: {len(invalid)} fields need evidence review (INVALID_SOURCE_REFERENCE)"
            )
        for field in out.fields:
            if id(field) in invalid:
                continue
            checkbox_grounding[id(field)] = ground_selection_mark(
                layout,
                field,
                field.unit_index,
                allowed_indexes={index + lo for index in ch.unit_indexes},
            )
        per_chunk.append(out.fields)
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
        original = rf.selected_candidate if rf else fo
        evidence_invalid = id(original) in invalid_evidence
        claimed, checkbox_hit = checkbox_grounding.get(id(original), (False, None))
        g = (
            None
            if evidence_invalid or spec.type == "list"
            else (
                checkbox_hit
                if claimed
                else ground(layout, fo, fo.unit_index, allowed_indexes=set(range(lo, hi + 1)))
            )
        )
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
        outcome = route(
            cfg.routing,
            field=spec.name,
            score=fo.confidence,
            grounded=g is not None,
            validation_status=vo.status,
            disagreement=bool(rf and rf.conflict),
        )
        if spec.type == "list" and fo.value not in (None, ""):
            outcome = "human_review"
            vo.messages.append(LIST_REVIEW)
            if vo.status == "passed":
                vo.status = "warning"
            if rf and rf.conflict:
                vo.messages.append(LIST_CONFLICT)
        if evidence_invalid:
            vo.messages.append(EVIDENCE_REVIEW_MESSAGE)
            vo.status = "failed"
            outcome = "human_review"
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
                validation_status=vo.status if vo.messages or vo.status != "passed" else "passed",
                validation_messages=vo.messages,
                suggested_correction=vo.suggested_correction,
                grounding=g,
                review_outcome=outcome,
                segment_index=segment_index,
                candidates=[c.model_dump() for c in (rf.candidates if rf else [])],
                conflict=bool(rf and rf.conflict),
            )
        )
    return result
