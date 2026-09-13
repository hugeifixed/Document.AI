"""Shared extraction pipeline used by every extraction-capable strategy:
preserved text → chunk plan → LLM per chunk (Pydantic ExtractionOut) →
reconcile → ground → validate → route. Invalid model output is caught per
chunk and recorded; it never crashes the document."""

from __future__ import annotations

from docai.exceptions import InvalidModelOutput
from docai.grounding.locate import locate_in_page, locate_in_sheet
from docai.grounding.sources import cited_unit, validate_sources
from docai.layout.chunk import plan_chunks
from docai.layout.preserve import preserve
from docai.layout.reconcile import reconcile
from docai.schemas.config import ExtractionSchemaConfig, FieldSpec
from docai.schemas.layout import LayoutDocument, LayoutPage
from docai.schemas.llm import ExtractionOut, FieldOut
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
    fblock = fields_block(schema.fields, guidance)
    for ch in plan.chunks:
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
            res = ctx.llm.invoke(call)
            for field in res.parsed.fields:
                validate_sources(
                    layout,
                    field.sources,
                    unit_index=field.unit_index,
                    allowed_indexes={index + lo for index in ch.unit_indexes},
                )
        except InvalidModelOutput as exc:
            result.warnings.append(
                f"chunk {ch.index}: invalid model output routed to review ({exc.error_code})"
            )
            result.raw_responses.append(
                {"stage": "extraction", "chunk": ch.index, "error": exc.error_code}
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
        per_chunk.append(out.fields)
        deployment = res.model_deployment
    if not per_chunk:
        # every chunk failed: emit null fields routed to review
        per_chunk.append([FieldOut(name=f.name, value=None, confidence=0.0) for f in schema.fields])
        deployment = ""

    merged = reconcile(per_chunk, reconciliation_policy)
    values = {name: rf.field.value for name, rf in merged.items()}
    for spec in schema.fields:
        rf = merged.get(spec.name)
        fo = rf.field if rf else FieldOut(name=spec.name, value=None, confidence=0.0)
        g = ground(layout, fo, fo.unit_index, allowed_indexes=set(range(lo, hi + 1)))
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
                candidates=[c.model_dump() for c in (rf.candidates if rf else [])][:5],
                conflict=bool(rf and rf.conflict),
            )
        )
    return result
