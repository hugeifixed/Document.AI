"""Generic, deterministic layout preservation (NO LLM). Renders a normalized
LayoutDocument into text an LLM can reason over without losing structure:

  * reading order is respected (paragraphs and tables interleaved as DI saw them)
  * tables become markdown with row/col spans expanded; each cell keeps its
    stable id in a compact legend so values stay citable
  * form-style pages: lines whose boxes share a y-band are linked into one
    row ("Label ... Value") so key/value pairs are not split apart
  * every unit is prefixed with a header carrying its stable id
  * spreadsheets render row-major with cell refs

Stable ids in the output are what the model cites back (SourceRef.ids)."""

from __future__ import annotations

from docai.schemas.config import LayoutPreservationConfig
from docai.schemas.layout import LayoutDocument, LayoutPage, LayoutSheet, Line, SheetCell, Table

UNIT_SEP = "\f"  # form feed between units; also lets the mock locate unit indexes


def _table_markdown(t: Table, with_ids: bool) -> str:
    grid: list[list[str]] = [["" for _ in range(t.col_count)] for _ in range(t.row_count)]
    ids: dict[tuple[int, int], str] = {}
    for c in t.cells:
        for r in range(c.row, min(c.row + c.row_span, t.row_count)):
            for k in range(c.col, min(c.col + c.col_span, t.col_count)):
                grid[r][k] = c.text.replace("|", "\\|").replace("\n", " ")
        ids[(c.row, c.col)] = c.id
    lines = [f"[table {t.id}]"]
    if t.row_count:
        lines.append("| " + " | ".join(grid[0]) + " |")
        lines.append("|" + "---|" * t.col_count)
        for row in grid[1:]:
            lines.append("| " + " | ".join(row) + " |")
    if with_ids:
        legend = ", ".join(f"r{r}c{k}={cid}" for (r, k), cid in sorted(ids.items())[:60])
        lines.append(f"[cells {legend}]")
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


def preserve_page(page: LayoutPage, cfg: LayoutPreservationConfig) -> str:
    if page.excluded_from_analysis:
        return ""
    parts = [f"=== PAGE {page.number} (unit {page.index}) ==="]
    tables = {t.id: t for t in page.tables}
    paras = {p.id: p for p in page.paragraphs}
    table_span_ranges = [
        (
            min([c.span.offset for c in t.cells if c.span] or [10**9]),
            max([c.span.offset + c.span.length for c in t.cells if c.span] or [-1]),
        )
        for t in page.tables
    ]

    def in_table(p):
        if not p.span:
            return False
        return any(a <= p.span.offset < b for a, b in table_span_ranges)

    if cfg.link_row_bands and page.lines and page.lines[0].polygon:
        # form-style rendering: bands of lines, tables inserted where they occur
        emitted_tables = set()
        bands = _row_bands(page, cfg.row_band_tolerance)
        for band in bands:
            band.sort(key=lambda ln: ln.polygon[0])
            row = "   ".join(ln.text for ln in band)
            ids = " ".join(ln.id for ln in band) if cfg.include_source_ids else ""
            # if any line of this band is part of a table, emit the table once instead
            t_hit = None
            for ln in band:
                if ln.span:
                    for (a, b), t in zip(table_span_ranges, page.tables, strict=True):
                        if a <= ln.span.offset < b:
                            t_hit = t
                            break
                if t_hit:
                    break
            if t_hit:
                if t_hit.id not in emitted_tables:
                    parts.append(_table_markdown(t_hit, cfg.include_source_ids))
                    emitted_tables.add(t_hit.id)
                continue
            parts.append(f"{row}  [{ids}]" if ids else row)
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
                if in_table(p):
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
