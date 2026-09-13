"""Capture versioned ground truth through one source-aware service seam."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from django.db import transaction

from docai.exceptions import NotFound, SpanMappingFailed, ValidationFailed
from docai.grounding.span_mapping import map_pdfjs_selection, map_word_ids, normalize_pdfjs_rects
from docai.models import (
    LABEL_KIND,
    LABEL_STATUS,
    Document,
    GroundTruthLabel,
    SourceSpan,
    SourceUnit,
)
from docai.schemas.layout import LayoutPage, LayoutSheet
from docai.validation.normalize import normalize_value

from . import audit
from .layouts import artifact_for_document, load_layout, read_artifact_layout

_REQUIRED_FIELDS = {
    "pdfjs": ("field_name", "unit_index", "text", "rects", "page_width_pt", "page_height_pt"),
    "word_ids": ("field_name", "unit_index", "word_ids"),
    "cells": ("field_name", "unit_index", "cell_range"),
    "absent": ("field_name",),
    "category": ("category",),
}


@dataclass(slots=True)
class _CapturedEvidence:
    label: dict[str, Any]
    audit_after: dict[str, Any]
    span: dict[str, Any] | None = None
    version_scope: dict[str, Any] = field(default_factory=dict)


def _document(value: Any) -> Document:
    if isinstance(value, Document):
        return value
    try:
        return Document.objects.get(pk=value)
    except (Document.DoesNotExist, ValueError, TypeError):
        raise NotFound("That document does not exist.") from None


def _unit(doc: Document, index: int, data: Mapping[str, Any]) -> SourceUnit:
    try:
        return SourceUnit.objects.get(
            document=doc, index=index, layout_artifact=data.get("_artifact")
        )
    except SourceUnit.DoesNotExist:
        raise NotFound("That page/sheet does not exist for this document.") from None


def _validate_capture(data: Mapping[str, Any]) -> str:
    mode = str(data.get("mode", ""))
    required = _REQUIRED_FIELDS.get(mode)
    if required is None:
        raise ValidationFailed(errors={"mode": "Choose a supported label capture mode."})
    missing = [name for name in required if name not in data]
    if "document" not in data:
        missing.insert(0, "document")
    if missing:
        raise ValidationFailed(
            errors=dict.fromkeys(missing, f"This field is required for mode '{mode}'.")
        )
    return mode


def _next_version(doc: Document, evidence: _CapturedEvidence) -> int:
    Document.objects.select_for_update().only("pk").get(pk=doc.pk)
    scope = evidence.version_scope
    queryset = GroundTruthLabel.objects.filter(
        document=doc,
        kind=evidence.label["kind"],
        field_name=evidence.label.get("field_name", ""),
    )
    if category := scope.get("category"):
        queryset = queryset.filter(category=category)
    if (unit_index := scope.get("unit_index")) is not None:
        queryset = queryset.filter(unit__index=unit_index)
    if scope.get("segment_start") is not None:
        queryset = queryset.filter(
            segment_start=scope["segment_start"], segment_end=scope.get("segment_end")
        )
    latest_version = queryset.order_by("-version").values_list("version", flat=True).first() or 0
    unit = evidence.label.get("unit")
    if unit is not None:
        queryset = queryset.filter(unit__layout_artifact_id=unit.layout_artifact_id)
    else:
        queryset = queryset.filter(unit__isnull=True)
    previous = queryset.order_by("-version").first()
    if previous and previous.status != LABEL_STATUS.superseded:
        previous.status = LABEL_STATUS.superseded
        previous.save(update_fields=["status", "modified"])
    return latest_version + 1


def _pdfjs_evidence(doc: Document, data: Mapping[str, Any]) -> _CapturedEvidence:
    unit_index = int(data["unit_index"])
    layout = read_artifact_layout(data["_artifact"]) if data.get("_artifact") else load_layout(doc)
    if not layout or unit_index >= len(layout.units):
        raise SpanMappingFailed("No page layout is available for this document yet.")
    page = layout.units[unit_index]
    if not isinstance(page, LayoutPage):
        raise SpanMappingFailed("No page layout is available for this document yet.")
    if not page.has_text_layer:
        raise SpanMappingFailed("Use OCR word selection for this scanned page.")
    text = str(data["text"])
    rects = list(data["rects"])
    page_width = float(data["page_width_pt"])
    page_height = float(data["page_height_pt"])
    normalized_rects = normalize_pdfjs_rects(rects, page_width, page_height)
    mapped = map_pdfjs_selection(page, text, normalized_rects)
    field_name = str(data["field_name"])
    expected_value = data.get("expected_value") or text
    unit = _unit(doc, unit_index, data)
    return _CapturedEvidence(
        label={
            "unit": unit,
            "kind": LABEL_KIND.field,
            "field_name": field_name,
            "expected_value": expected_value,
            "normalized_value": normalize_value(
                expected_value, str(data.get("field_type", "string"))
            ),
            "is_absent": False,
            "pdfjs_span": {
                "page": unit_index,
                "text": text,
                "rects": rects,
                "rects_normalized": normalized_rects,
                "page_size_pt": [page_width, page_height],
            },
            "azure_span": {
                key: mapped.get(key)
                for key in ("word_ids", "polygon", "offset_start", "offset_end")
            },
            "mapping_method": mapped["method"],
            "match_score": mapped["score"],
            "mapping_exceptions": mapped.get("exceptions", []),
            "status": LABEL_STATUS.final if data.get("finalize", True) else LABEL_STATUS.draft,
        },
        span={
            "unit": unit,
            "text": text[:500],
            "offset_start": mapped.get("offset_start"),
            "offset_end": mapped.get("offset_end"),
            "polygon": mapped.get("polygon", []),
            "word_ids": mapped.get("word_ids", []),
            "mapping_method": mapped["method"],
            "match_score": mapped["score"],
            "exceptions": mapped.get("exceptions", []),
            "origin": "pdfjs",
        },
        audit_after={"field": field_name, "method": mapped["method"], "score": mapped["score"]},
    )


def _word_evidence(doc: Document, data: Mapping[str, Any]) -> _CapturedEvidence:
    unit_index = int(data["unit_index"])
    layout = read_artifact_layout(data["_artifact"]) if data.get("_artifact") else load_layout(doc)
    if not layout or unit_index >= len(layout.units):
        raise SpanMappingFailed("No layout is available for this document yet.")
    page = layout.units[unit_index]
    if not isinstance(page, LayoutPage):
        raise SpanMappingFailed("Word-box labeling applies to pages, not worksheets.")
    mapped = map_word_ids(page, list(data["word_ids"]))
    if mapped["method"] == "none":
        raise SpanMappingFailed(errors={"word_ids": "unknown ids"})
    field_name = str(data["field_name"])
    expected_value = data.get("expected_value") or ""
    unit = _unit(doc, unit_index, data)
    return _CapturedEvidence(
        label={
            "unit": unit,
            "kind": LABEL_KIND.field,
            "field_name": field_name,
            "expected_value": expected_value,
            "normalized_value": normalize_value(
                expected_value, str(data.get("field_type", "string"))
            ),
            "pdfjs_span": {},
            "azure_span": {
                key: mapped.get(key)
                for key in ("word_ids", "polygon", "offset_start", "offset_end", "text")
            },
            "mapping_method": mapped["method"],
            "match_score": mapped["score"],
            "mapping_exceptions": [],
            "status": LABEL_STATUS.final if data.get("finalize", True) else LABEL_STATUS.draft,
        },
        span={
            "unit": unit,
            "text": mapped.get("text", "")[:500],
            "offset_start": mapped.get("offset_start"),
            "offset_end": mapped.get("offset_end"),
            "polygon": mapped.get("polygon", []),
            "word_ids": mapped["word_ids"],
            "mapping_method": "word_boxes",
            "match_score": 1.0,
            "origin": "azure",
        },
        audit_after={"field": field_name, "method": "word_boxes"},
    )


def _cell_evidence(doc: Document, data: Mapping[str, Any]) -> _CapturedEvidence:
    unit_index = int(data["unit_index"])
    layout = read_artifact_layout(data["_artifact"]) if data.get("_artifact") else load_layout(doc)
    if not layout or unit_index >= len(layout.units):
        raise SpanMappingFailed("No worksheet layout is available for this document yet.")
    sheet = layout.units[unit_index]
    if not isinstance(sheet, LayoutSheet):
        raise SpanMappingFailed("No worksheet layout is available for this document yet.")
    cell_range = str(data["cell_range"])
    cells = [cell for cell in sheet.cells if cell.ref in _expand_range(cell_range)]
    displayed = " ".join(cell.value or "" for cell in cells)
    field_name = str(data["field_name"])
    expected_value = data.get("expected_value") or ""
    unit = _unit(doc, unit_index, data)
    score = 1.0 if cells else 0.0
    return _CapturedEvidence(
        label={
            "unit": unit,
            "kind": LABEL_KIND.field,
            "field_name": field_name,
            "expected_value": expected_value,
            "normalized_value": normalize_value(
                expected_value, str(data.get("field_type", "string"))
            ),
            "cell_range": cell_range,
            "azure_span": {
                "workbook": doc.original_filename,
                "sheet": sheet.name,
                "sheet_index": unit_index,
                "cell_range": cell_range,
                "displayed_value": displayed,
                "formulas": {cell.ref: cell.formula for cell in cells if cell.formula},
                "cell_ids": [cell.id for cell in cells],
            },
            "mapping_method": "cell_range",
            "match_score": score,
            "mapping_exceptions": [] if cells else ["range has no populated cells"],
            "status": LABEL_STATUS.final if data.get("finalize", True) else LABEL_STATUS.draft,
        },
        span={
            "unit": unit,
            "text": displayed[:500],
            "cell_range": cell_range,
            "word_ids": [cell.id for cell in cells],
            "mapping_method": "cell_range",
            "match_score": score,
            "origin": "human",
        },
        audit_after={"field": field_name, "cell_range": cell_range},
    )


def _absent_evidence(data: Mapping[str, Any]) -> _CapturedEvidence:
    field_name = str(data["field_name"])
    return _CapturedEvidence(
        label={
            "kind": LABEL_KIND.field,
            "field_name": field_name,
            "expected_value": None,
            "normalized_value": None,
            "is_absent": True,
            "status": LABEL_STATUS.final,
        },
        audit_after={"field": field_name, "absent": True},
    )


def _category_evidence(data: Mapping[str, Any]) -> _CapturedEvidence:
    segment_start = data.get("segment_start")
    segment_end = data.get("segment_end")
    category = str(data["category"])
    return _CapturedEvidence(
        label={
            "kind": LABEL_KIND.segment if segment_start is not None else LABEL_KIND.category,
            "category": category,
            "segment_start": segment_start,
            "segment_end": segment_end,
            "status": LABEL_STATUS.final,
        },
        version_scope={"segment_start": segment_start, "segment_end": segment_end},
        audit_after={"category": category, "range": [segment_start, segment_end]},
    )


@transaction.atomic
def capture_label(data: Mapping[str, Any], *, user=None) -> GroundTruthLabel:
    """Validate, map, version, persist, and audit one label capture request."""
    mode = _validate_capture(data)
    doc = _document(data["document"])
    artifact = artifact_for_document(doc, data.get("run"))
    if artifact is None and data.get("run") and mode in {"pdfjs", "word_ids", "cells"}:
        raise SpanMappingFailed("No layout is available for this document in the selected run.")
    data = {**data, "_artifact": artifact}
    mapper = {
        "pdfjs": _pdfjs_evidence,
        "word_ids": _word_evidence,
        "cells": _cell_evidence,
    }.get(mode)
    captured = (
        mapper(doc, data)
        if mapper
        else (_absent_evidence(data) if mode == "absent" else _category_evidence(data))
    )
    label = GroundTruthLabel.objects.create(
        document=doc,
        labeler=user,
        notes=str(data.get("notes", "")),
        version=_next_version(doc, captured),
        created_by=user,
        **captured.label,
    )
    if captured.span is not None:
        SourceSpan.objects.create(label=label, created_by=user, **captured.span)
    audit.record(user, "label.created", label, after=captured.audit_after)
    return label


# Focused Python entry points still cross the same invariant-owning seam.
def label_from_pdfjs(doc: Document, **values) -> GroundTruthLabel:
    user = values.pop("user", None)
    return capture_label({"document": doc, "mode": "pdfjs", **values}, user=user)


def label_from_word_ids(doc: Document, **values) -> GroundTruthLabel:
    user = values.pop("user", None)
    return capture_label({"document": doc, "mode": "word_ids", **values}, user=user)


def label_from_cells(doc: Document, **values) -> GroundTruthLabel:
    user = values.pop("user", None)
    return capture_label({"document": doc, "mode": "cells", **values}, user=user)


def label_absent(doc: Document, **values) -> GroundTruthLabel:
    user = values.pop("user", None)
    return capture_label({"document": doc, "mode": "absent", **values}, user=user)


def label_category(doc: Document, **values) -> GroundTruthLabel:
    user = values.pop("user", None)
    return capture_label({"document": doc, "mode": "category", **values}, user=user)


def _expand_range(value: str) -> set[str]:
    match = re.match(r"^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$", value.upper())
    if not match:
        return {value.upper()}
    first_column, first_row, last_column, last_row = (
        match.group(1),
        int(match.group(2)),
        match.group(3) or match.group(1),
        int(match.group(4) or match.group(2)),
    )

    def column_index(column: str) -> int:
        result = 0
        for character in column:
            result = result * 26 + (ord(character) - 64)
        return result

    def column_name(index: int) -> str:
        result = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            result = chr(65 + remainder) + result
        return result

    return {
        f"{column_name(column)}{row}"
        for column in range(column_index(first_column), column_index(last_column) + 1)
        for row in range(first_row, last_row + 1)
    }
