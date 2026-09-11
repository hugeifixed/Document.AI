"""Ground-truth creation from three selection sources, each producing a label
that stores BOTH the UI-derived span and the reconciled layout span with
method, score and exceptions."""

from __future__ import annotations

from docai.exceptions import NotFound, SpanMappingFailed
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
from .layouts import load_layout


def _unit(doc: Document, index: int) -> SourceUnit:
    try:
        return SourceUnit.objects.get(document=doc, index=index)
    except SourceUnit.DoesNotExist:
        raise NotFound("That page/sheet does not exist for this document.") from None


def _next_version(doc, kind, field_name, category, unit_index):
    qs = GroundTruthLabel.objects.filter(
        document=doc, kind=kind, field_name=field_name or "", category=category or ""
    )
    if unit_index is not None:
        qs = qs.filter(unit__index=unit_index)
    last = qs.order_by("-version").first()
    if last and last.status != LABEL_STATUS.superseded:
        last.status = LABEL_STATUS.superseded
        last.save(update_fields=["status", "modified"])
    return (last.version + 1) if last else 1


def label_from_pdfjs(
    doc: Document,
    *,
    unit_index: int,
    field_name: str,
    expected_value: str,
    text: str,
    rects: list[dict],
    page_width_pt: float,
    page_height_pt: float,
    field_type: str = "string",
    user=None,
    notes: str = "",
    finalize: bool = True,
) -> GroundTruthLabel:
    layout = load_layout(doc)
    if not layout or unit_index >= len(layout.units):
        raise SpanMappingFailed("No page layout is available for this document yet.")
    page = layout.units[unit_index]
    if not isinstance(page, LayoutPage):
        raise SpanMappingFailed("No page layout is available for this document yet.")
    rects_norm = normalize_pdfjs_rects(rects, page_width_pt, page_height_pt)
    mapped = map_pdfjs_selection(page, text, rects_norm)
    unit = _unit(doc, unit_index)
    lb = GroundTruthLabel.objects.create(
        document=doc,
        unit=unit,
        kind=LABEL_KIND.field,
        field_name=field_name,
        expected_value=expected_value,
        normalized_value=normalize_value(expected_value, field_type),
        is_absent=False,
        pdfjs_span={
            "page": unit_index,
            "text": text,
            "rects": rects,
            "rects_normalized": rects_norm,
            "page_size_pt": [page_width_pt, page_height_pt],
        },
        azure_span={
            k: mapped.get(k) for k in ("word_ids", "polygon", "offset_start", "offset_end")
        },
        mapping_method=mapped["method"],
        match_score=mapped["score"],
        mapping_exceptions=mapped.get("exceptions", []),
        labeler=user,
        version=_next_version(doc, LABEL_KIND.field, field_name, "", None),
        status=LABEL_STATUS.final if finalize else LABEL_STATUS.draft,
        notes=notes,
        created_by=user,
    )
    SourceSpan.objects.create(
        unit=unit,
        label=lb,
        text=text[:500],
        offset_start=mapped.get("offset_start"),
        offset_end=mapped.get("offset_end"),
        polygon=mapped.get("polygon", []),
        word_ids=mapped.get("word_ids", []),
        mapping_method=mapped["method"],
        match_score=mapped["score"],
        exceptions=mapped.get("exceptions", []),
        origin="pdfjs",
        created_by=user,
    )
    audit.record(
        user,
        "label.created",
        lb,
        after={"field": field_name, "method": mapped["method"], "score": mapped["score"]},
    )
    return lb


def label_from_word_ids(
    doc: Document,
    *,
    unit_index: int,
    field_name: str,
    expected_value: str,
    word_ids: list[str],
    field_type: str = "string",
    user=None,
    notes: str = "",
    finalize: bool = True,
) -> GroundTruthLabel:
    """Image-only pages: selection is made on the layout's own word boxes."""
    layout = load_layout(doc)
    if not layout or unit_index >= len(layout.units):
        raise SpanMappingFailed("No layout is available for this document yet.")
    page = layout.units[unit_index]
    if not isinstance(page, LayoutPage):
        raise SpanMappingFailed("Word-box labeling applies to pages, not worksheets.")
    mapped = map_word_ids(page, word_ids)
    if mapped["method"] == "none":
        raise SpanMappingFailed(errors={"word_ids": "unknown ids"})
    unit = _unit(doc, unit_index)
    lb = GroundTruthLabel.objects.create(
        document=doc,
        unit=unit,
        kind=LABEL_KIND.field,
        field_name=field_name,
        expected_value=expected_value,
        normalized_value=normalize_value(expected_value, field_type),
        pdfjs_span={},
        azure_span={
            k: mapped.get(k) for k in ("word_ids", "polygon", "offset_start", "offset_end", "text")
        },
        mapping_method=mapped["method"],
        match_score=mapped["score"],
        mapping_exceptions=[],
        labeler=user,
        version=_next_version(doc, LABEL_KIND.field, field_name, "", None),
        status=LABEL_STATUS.final if finalize else LABEL_STATUS.draft,
        notes=notes,
        created_by=user,
    )
    SourceSpan.objects.create(
        unit=unit,
        label=lb,
        text=mapped.get("text", "")[:500],
        offset_start=mapped.get("offset_start"),
        offset_end=mapped.get("offset_end"),
        polygon=mapped.get("polygon", []),
        word_ids=mapped["word_ids"],
        mapping_method="word_boxes",
        match_score=1.0,
        origin="azure",
        created_by=user,
    )
    audit.record(user, "label.created", lb, after={"field": field_name, "method": "word_boxes"})
    return lb


def label_from_cells(
    doc: Document,
    *,
    unit_index: int,
    field_name: str,
    expected_value: str,
    cell_range: str,
    field_type: str = "string",
    user=None,
    notes: str = "",
    finalize: bool = True,
) -> GroundTruthLabel:
    layout = load_layout(doc)
    if not layout or unit_index >= len(layout.units):
        raise SpanMappingFailed("No worksheet layout is available for this document yet.")
    sheet = layout.units[unit_index]
    if not isinstance(sheet, LayoutSheet):
        raise SpanMappingFailed("No worksheet layout is available for this document yet.")
    refs = _expand_range(cell_range)
    cells = [c for c in sheet.cells if c.ref in refs]
    unit = _unit(doc, unit_index)
    displayed = " ".join(c.value or "" for c in cells)
    lb = GroundTruthLabel.objects.create(
        document=doc,
        unit=unit,
        kind=LABEL_KIND.field,
        field_name=field_name,
        expected_value=expected_value,
        normalized_value=normalize_value(expected_value, field_type),
        cell_range=cell_range,
        azure_span={
            "workbook": doc.original_filename,
            "sheet": sheet.name,
            "sheet_index": unit_index,
            "cell_range": cell_range,
            "displayed_value": displayed,
            "formulas": {c.ref: c.formula for c in cells if c.formula},
            "cell_ids": [c.id for c in cells],
        },
        mapping_method="cell_range",
        match_score=1.0 if cells else 0.0,
        mapping_exceptions=[] if cells else ["range has no populated cells"],
        labeler=user,
        version=_next_version(doc, LABEL_KIND.field, field_name, "", None),
        status=LABEL_STATUS.final if finalize else LABEL_STATUS.draft,
        notes=notes,
        created_by=user,
    )
    SourceSpan.objects.create(
        unit=unit,
        label=lb,
        text=displayed[:500],
        cell_range=cell_range,
        word_ids=[c.id for c in cells],
        mapping_method="cell_range",
        match_score=lb.match_score,
        origin="human",
        created_by=user,
    )
    audit.record(user, "label.created", lb, after={"field": field_name, "cell_range": cell_range})
    return lb


def label_absent(doc: Document, *, field_name: str, user=None, notes: str = "") -> GroundTruthLabel:
    lb = GroundTruthLabel.objects.create(
        document=doc,
        kind=LABEL_KIND.field,
        field_name=field_name,
        expected_value=None,
        normalized_value=None,
        is_absent=True,
        labeler=user,
        version=_next_version(doc, LABEL_KIND.field, field_name, "", None),
        status=LABEL_STATUS.final,
        notes=notes,
        created_by=user,
    )
    audit.record(user, "label.created", lb, after={"field": field_name, "absent": True})
    return lb


def label_category(
    doc: Document,
    *,
    category: str,
    segment_start: int | None = None,
    segment_end: int | None = None,
    user=None,
    notes: str = "",
) -> GroundTruthLabel:
    kind = LABEL_KIND.segment if segment_start is not None else LABEL_KIND.category
    lb = GroundTruthLabel.objects.create(
        document=doc,
        kind=kind,
        category=category,
        segment_start=segment_start,
        segment_end=segment_end,
        labeler=user,
        status=LABEL_STATUS.final,
        notes=notes,
        version=1,
        created_by=user,
    )
    audit.record(
        user,
        "label.created",
        lb,
        after={"category": category, "range": [segment_start, segment_end]},
    )
    return lb


def _expand_range(rng: str) -> set[str]:
    import re

    m = re.match(r"^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$", rng.upper())
    if not m:
        return {rng.upper()}
    c1, r1, c2, r2 = (
        m.group(1),
        int(m.group(2)),
        m.group(3) or m.group(1),
        int(m.group(4) or m.group(2)),
    )

    def col_idx(s):
        n = 0
        for ch in s:
            n = n * 26 + (ord(ch) - 64)
        return n

    def col_str(n):
        s = ""
        while n:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s

    return {
        f"{col_str(c)}{r}" for c in range(col_idx(c1), col_idx(c2) + 1) for r in range(r1, r2 + 1)
    }
