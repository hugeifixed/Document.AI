"""Verify selection-mark claims without guessing labels or searching ordinary text."""

from __future__ import annotations

import math
import re

from docai.schemas.layout import LayoutDocument, LayoutPage
from docai.schemas.llm import FieldOut

_MARK_ID = re.compile(r"p([1-9][0-9]*):sm(0|[1-9][0-9]*)", re.IGNORECASE)
_NAME = re.compile(r"checkbox (p[1-9][0-9]*:sm(?:0|[1-9][0-9]*))", re.IGNORECASE)
_MARKER = re.compile(
    r"\[checkbox (p[1-9][0-9]*:sm(?:0|[1-9][0-9]*)): (selected|unselected)\]",
    re.IGNORECASE,
)
_CLAIM = re.compile(r"\bcheckbox\s+p[^\s]*:sm|\[checkbox\b", re.IGNORECASE)


def _canonical(field: FieldOut) -> tuple[bool, list[tuple[str, str | None]], bool]:
    refs = []
    claimed = False
    valid = True
    for text, is_name in [(field.name, True), (field.evidence, False)] + [
        (source.quote, False) for source in field.sources
    ]:
        text = text.strip()
        marker = _MARKER.fullmatch(text)
        name = _NAME.fullmatch(text) if is_name else None
        match = marker or name
        if match is not None:
            refs.append((match[1].lower(), marker[2].lower() if marker else None))
            claimed = True
        elif _CLAIM.search(text):
            claimed, valid = True, False
    return claimed, refs, valid


def _valid_polygon(polygon: list[float]) -> bool:
    # Azure marks are quadrilaterals. Require a finite, normalized, convex area;
    # repeated vertices, collinear edges and crossing/bow-tie boxes are invalid.
    if len(polygon) != 8 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in polygon):
        return False
    points = list(zip(polygon[::2], polygon[1::2], strict=True))
    crosses = []
    for i in range(4):
        a, b, c = points[i], points[(i + 1) % 4], points[(i + 2) % 4]
        crosses.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
    return all(v > 0 for v in crosses) or all(v < 0 for v in crosses)


def ground_selection_mark(
    layout: LayoutDocument,
    field: FieldOut,
    unit_hint: int | None,
    *,
    allowed_indexes: set[int] | None = None,
) -> tuple[bool, dict | None]:
    """Return (claimed, hit): a failed claim must never fall through to text."""
    claimed, canonical, valid = _canonical(field)
    explicit = {
        (source.unit_index, source_id)
        for source in field.sources
        for source_id in source.ids
        if _MARK_ID.fullmatch(source_id)
        or any(mark.id == source_id for page in layout.pages for mark in page.selection_marks)
    }
    claimed = claimed or bool(explicit)
    if not claimed:
        return False, None
    state = (field.value or "").strip().lower()
    if not valid or state not in {"selected", "unselected"}:
        return True, None
    if any(marker_state is not None and marker_state != state for _, marker_state in canonical):
        return True, None
    candidates = explicit or {
        (int(mark_id.split(":")[0][1:]) - 1, mark_id) for mark_id, _ in canonical
    }
    if len(candidates) != 1:
        return True, None
    index, mark_id = next(iter(candidates))
    if any(ref_id != mark_id for ref_id, _ in canonical):
        return True, None
    if unit_hint is not None and unit_hint != index:
        return True, None
    if allowed_indexes is not None and index not in allowed_indexes:
        return True, None
    # Page-only citations constrain fallback too. Non-mark ids cannot authorize
    # substitution with a mark just because a canonical marker was also emitted.
    if any(
        source.unit_index != index or (source.ids and mark_id not in source.ids)
        for source in field.sources
    ):
        return True, None
    pages = [page for page in layout.units if isinstance(page, LayoutPage) and page.index == index]
    if len(pages) != 1:
        return True, None
    page = pages[0]
    if page.excluded_from_analysis or page.number != index + 1:
        return True, None
    if not _MARK_ID.fullmatch(mark_id) or not mark_id.startswith(f"p{page.number}:sm"):
        return True, None
    marks = [mark for mark in page.selection_marks if mark.id == mark_id]
    if len(marks) != 1 or marks[0].state != state or not _valid_polygon(marks[0].polygon):
        return True, None
    mark = marks[0]
    return True, {
        "unit_index": index,
        "word_ids": [mark.id],
        "polygon": list(mark.polygon),
        "method": "selection_mark",
        "score": 1.0,
        # DI mark spans refer to generated content tokens, not literal page text.
        "offset_start": None,
        "offset_end": None,
    }
