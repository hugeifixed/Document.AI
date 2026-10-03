"""Generic, deterministic layout preservation (NO LLM). Renders a normalized
LayoutDocument into text an LLM can reason over without losing structure:

  * reading order is respected (paragraphs and tables interleaved as DI saw them)
  * tables become markdown with row/col spans expanded; each cell keeps its
    stable id beside its value, including every expanded merged-cell position
  * form-style pages: lines whose boxes share a y-band are linked into one
    row ("Label ... Value") so key/value pairs are not split apart
  * every unit is prefixed with a header carrying its stable id
  * spreadsheets render row-major with cell refs

Stable ids in the output are what the model cites back (SourceRef.ids)."""

from __future__ import annotations

from docai.schemas.config import LayoutPreservationConfig
from docai.schemas.layout import (
    LayoutDocument,
    LayoutPage,
    LayoutSheet,
    Line,
    SheetCell,
    Span,
    Table,
)

UNIT_SEP = "\f"  # form feed between units; also lets the mock locate unit indexes


def _table_markdown(t: Table, with_ids: bool) -> str:
    grid: list[list[str]] = [["" for _ in range(t.col_count)] for _ in range(t.row_count)]
    for c in t.cells:
        text = c.text.replace("|", "\\|").replace("\n", " ")
        # Expanded positions are views of the same source cell, not new cells.
        # Keep its canonical ID beside every copy, including beyond 60 cells.
        value = f"{text} [{c.id}]" if with_ids else text
        for r in range(c.row, min(c.row + c.row_span, t.row_count)):
            for k in range(c.col, min(c.col + c.col_span, t.col_count)):
                grid[r][k] = value
    lines = [f"[table {t.id}]"]
    if t.row_count:
        lines.append("| " + " | ".join(grid[0]) + " |")
        lines.append("|" + "---|" * t.col_count)
        for row in grid[1:]:
            lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _row_bands(page: LayoutPage, tol: float) -> list[list[Line]]:
    """Group lines by vertical band so 'Label   Value' pairs stay together."""
    lines = [ln for ln in page.lines if ln.polygon]
    if not lines:
        return []

    def cy(ln):
        ys = ln.polygon[1::2]
        return sum(ys) / len(ys)

    lines.sort(key=lambda ln: (cy(ln), ln.polygon[0]))
    bands: list[list[Line]] = []
    cur: list[Line] = []
    cur_y: float | None = None
    for ln in lines:
        y = cy(ln)
        if cur_y is None or abs(y - cur_y) <= tol:
            cur.append(ln)
            cur_y = y if cur_y is None else (cur_y + y) / 2
        else:
            bands.append(cur)
            cur, cur_y = [ln], y
    if cur:
        bands.append(cur)
    return bands


def _covered_by_cells(span: Span | None, ranges: list[tuple[int, int]], content: str) -> bool:
    """Only suppress text proven to be represented by actual table cells.

    The envelope around a table's spans can contain unrelated OCR text. Gaps
    between cells are safe to skip only when the page content proves they are
    whitespace. Missing spans/content therefore favor retaining source text.
    """
    if span is None or not span.length:
        return False
    cursor = span.offset
    end = span.offset + span.length

    def whitespace(start: int, stop: int) -> bool:
        return stop <= len(content) and not content[start:stop].strip()

    for start, stop in ranges:
        if stop <= cursor:
            continue
        if start >= end:
            break
        if start > cursor and not whitespace(cursor, start):
            return False
        cursor = min(end, stop)
        if cursor == end:
            return True
    return cursor > span.offset and whitespace(cursor, end)


def _overlaps_cells(span: Span | None, ranges: list[tuple[int, int]]) -> bool:
    return (
        span is not None
        and span.length > 0
        and any(span.offset < end and start < span.offset + span.length for start, end in ranges)
    )


def preserve_page(page: LayoutPage, cfg: LayoutPreservationConfig) -> str:
    if page.excluded_from_analysis:
        return ""
    parts = [f"=== PAGE {page.number} (unit {page.index}) ==="]
    tables = {t.id: t for t in page.tables}
    paras = {p.id: p for p in page.paragraphs}
    table_spans = {
        t.id: sorted(
            (c.span.offset, c.span.offset + c.span.length)
            for c in t.cells
            if c.span is not None and c.span.length > 0
        )
        for t in page.tables
    }
    cell_ranges = sorted(span for ranges in table_spans.values() for span in ranges)

    if cfg.link_row_bands and page.lines and page.lines[0].polygon:
        # form-style rendering: bands of lines, tables inserted where they occur
        emitted_tables = set()
        bands = _row_bands(page, cfg.row_band_tolerance)
        for band in bands:
            band.sort(key=lambda ln: ln.polygon[0])
            # A partial table replaces only its own text, never the entire band.
            retained = [
                ln for ln in band if not _covered_by_cells(ln.span, cell_ranges, page.content)
            ]
            if retained:
                row = "   ".join(ln.text for ln in retained)
                ids = " ".join(ln.id for ln in retained) if cfg.include_source_ids else ""
                parts.append(f"{row}  [{ids}]" if ids else row)
            for t in page.tables:
                if t.id not in emitted_tables and any(
                    _overlaps_cells(ln.span, table_spans[t.id]) for ln in band
                ):
                    parts.append(_table_markdown(t, cfg.include_source_ids))
                    emitted_tables.add(t.id)
        for t in page.tables:
            if t.id not in emitted_tables:
                parts.append(_table_markdown(t, cfg.include_source_ids))
    else:
        for oid in page.reading_order or [p.id for p in page.paragraphs] + [
            t.id for t in page.tables
        ]:
            if oid in tables:
                parts.append(_table_markdown(tables[oid], cfg.include_source_ids))
            elif oid in paras:
                p = paras[oid]
                if cfg.drop_headers_footers and p.role in (
                    "pageHeader",
                    "pageFooter",
                    "pageNumber",
                ):
                    continue
                if _covered_by_cells(p.span, cell_ranges, page.content):
                    continue
                role = f"<{p.role}> " if p.role else ""
                parts.append(
                    f"{role}{p.text}  [{p.id}]" if cfg.include_source_ids else f"{role}{p.text}"
                )
        if not page.paragraphs and not page.tables and page.content:
            parts.append(page.content)
    for sm in page.selection_marks:
        parts.append(f"[checkbox {sm.id}: {sm.state}]")
    return "\n".join(parts)


def preserve_sheet(sheet: LayoutSheet, cfg: LayoutPreservationConfig) -> str:
    parts = [
        f"=== SHEET '{sheet.name}' (unit {sheet.index}, {sheet.row_count}x{sheet.col_count}) ==="
    ]
    if sheet.merged_ranges:
        parts.append(f"[merged {', '.join(sheet.merged_ranges[:30])}]")
    rows: dict[int, list[SheetCell]] = {}
    for c in sheet.cells:
        rows.setdefault(c.row, []).append(c)
    for r in sorted(rows):
        cells = sorted(rows[r], key=lambda c: c.col)
        seg: list[str] = []
        for c in cells:
            v = c.value if c.value is not None else ""
            f = f" (={c.formula[1:]})" if c.formula else ""
            seg.append(f"{c.ref}={v}{f}" if cfg.include_source_ids else v)
        parts.append(" | ".join(seg))
    return "\n".join(parts)


def preserve(doc: LayoutDocument, cfg: LayoutPreservationConfig | None = None) -> list[str]:
    """One preserved-text string per unit, in unit order."""
    cfg = cfg or LayoutPreservationConfig()
    out: list[str] = []
    for u in doc.units:
        out.append(preserve_page(u, cfg) if isinstance(u, LayoutPage) else preserve_sheet(u, cfg))
    return out


def join_units(unit_texts: list[str]) -> str:
    return UNIT_SEP.join(unit_texts)
