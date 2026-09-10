"""Exports: structured JSON (utf-8, ensure_ascii=False), CSV (utf-8 with BOM
for Excel), XLSX for tabular results. Nested structures are flattened with
dotted keys and every row keeps its source identifiers (document, unit, span)."""
from __future__ import annotations

import csv
import io
import json

from docai.models import ClassificationResult, ExtractedField, GroundTruthLabel, ReviewAction, Run, Segment, SourceSpan


def _span_ref(obj) -> dict:
    sp = obj.spans.select_related("unit").first() if hasattr(obj, "spans") else None
    if not sp:
        return {}
    return {"unit_index": sp.unit.index, "unit_kind": sp.unit.kind, "word_ids": sp.word_ids, "polygon": sp.polygon,
            "offset_start": sp.offset_start, "offset_end": sp.offset_end, "cell_range": sp.cell_range,
            "mapping_method": sp.mapping_method, "match_score": sp.match_score}


def run_package(run: Run) -> dict:
    """Everything about a run, JSON-serializable."""
    fields = [{
        "document_id": str(f.document_id), "document": f.document.original_filename, "segment_index": f.segment.index if f.segment else None,
        "name": f.name, "type": f.field_type, "raw_value": f.raw_value, "normalized_value": f.normalized_value,
        "reviewed_value": f.reviewed_value, "score": f.score, "source_text": f.source_text, "method": f.method,
        "strategy": f.strategy, "fallback_used": f.fallback_used, "model_deployment": f.model_deployment,
        "prompt": f"{f.prompt_version.name}@{f.prompt_version.version}" if f.prompt_version else None,
        "schema": f"{f.schema_version.name}@{f.schema_version.version}" if f.schema_version else None,
        "api_version": f.api_version, "validation_status": f.validation_status, "validation_messages": f.validation_messages,
        "suggested_correction": f.suggested_correction, "review_status": f.review_status, "grounded": f.grounded,
        "source": _span_ref(f),
    } for f in ExtractedField.objects.filter(run=run).select_related("document", "segment", "prompt_version", "schema_version")]
    classifications = [{
        "document_id": str(c.document_id), "document": c.document.original_filename, "segment_index": c.segment.index if c.segment else None,
        "category": c.category, "reviewed_category": c.reviewed_category, "score": c.score, "method": c.method,
        "rule_score": c.rule_score, "matched_evidence": c.matched_evidence, "excluded_evidence": c.excluded_evidence,
        "llm_evidence": c.llm_evidence, "rule_version": c.rule_version, "model_deployment": c.model_deployment,
        "review_status": c.review_status, "source": _span_ref(c),
    } for c in ClassificationResult.objects.filter(run=run).select_related("document", "segment")]
    segments = [{
        "document_id": str(s.document_id), "document": s.document.original_filename, "index": s.index,
        "start_unit": s.start_unit, "end_unit": s.end_unit, "category": s.category, "score": s.score, "method": s.method,
        "evidence": s.evidence, "review_status": s.review_status,
    } for s in Segment.objects.filter(run=run).select_related("document")]
    doc_ids = list(run.items.values_list("document_id", flat=True))
    labels = [{
        "document_id": str(l.document_id), "kind": l.kind, "field_name": l.field_name, "category": l.category,
        "expected_value": l.expected_value, "normalized_value": l.normalized_value, "is_absent": l.is_absent,
        "segment_start": l.segment_start, "segment_end": l.segment_end, "unit_index": l.unit.index if l.unit else None,
        "pdfjs_span": l.pdfjs_span, "azure_span": l.azure_span, "mapping_method": l.mapping_method, "match_score": l.match_score,
        "cell_range": l.cell_range, "version": l.version, "status": l.status, "labeler": l.labeler.username if l.labeler else None,
    } for l in GroundTruthLabel.objects.filter(document_id__in=doc_ids).select_related("unit", "labeler")]
    reviews = [{
        "action": a.action, "actor": a.actor.username if a.actor else None, "at": a.created.isoformat(),
        "field_id": str(a.field_id) if a.field_id else None, "classification_id": str(a.classification_id) if a.classification_id else None,
        "segment_id": str(a.segment_id) if a.segment_id else None, "before": a.before, "after": a.after, "reason": a.reason,
    } for a in ReviewAction.objects.filter(field__run=run).select_related("actor")]
    errors = [{"document_id": str(i.document_id), "document": i.document.original_filename, "status": i.status,
               "error_code": i.error_code, "error_message": i.error_message, "attempts": i.attempts, "retryable": i.retryable}
              for i in run.items.select_related("document") if i.error_code]
    return {"run": {"id": str(run.id), "name": run.name, "status": run.status, "workflow": run.workflow.name,
                    "workflow_version": run.workflow.version, "config_hash": run.config_hash,
                    "prompt_versions": run.prompt_versions, "schema_versions": run.schema_versions,
                    "model_deployment": run.model_deployment, "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None},
            "configuration_snapshot": run.config_snapshot, "metrics": run.metrics, "fields": fields,
            "classifications": classifications, "segments": segments, "ground_truth": labels, "reviews": reviews, "errors": errors,
            "flattening_note": "CSV/XLSX flatten nested objects with dotted keys (e.g. source.unit_index); lists are JSON strings."}


def to_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        elif isinstance(v, list):
            out[key] = json.dumps(v, ensure_ascii=False, default=str)
        else:
            out[key] = v
    return out


def rows_to_csv(rows: list[dict]) -> bytes:
    flat = [_flatten(r) for r in rows]
    cols = []
    for r in flat:
        for k in r:
            if k not in cols:
                cols.append(k)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in flat:
        w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def rows_to_xlsx(sheets: dict[str, list[dict]]) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name[:31])
        flat = [_flatten(r) for r in rows]
        cols = []
        for r in flat:
            for k in r:
                if k not in cols:
                    cols.append(k)
        ws.append(cols)
        for r in flat:
            ws.append([r.get(c) if not isinstance(r.get(c), (dict, list)) else json.dumps(r.get(c), ensure_ascii=False) for c in cols])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
