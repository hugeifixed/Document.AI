"""Excel → normalized layout with openpyxl (xlsx) / xlrd (xls). Reading with
these libraries never evaluates formulas or macros; we additionally REFUSE
workbooks with VBA, external links, or embedded objects (§7 safety)."""

from __future__ import annotations

import zipfile
from os import PathLike
from pathlib import Path
from typing import BinaryIO

from docai.exceptions import CorruptFile, UnsafeWorkbook
from docai.schemas.layout import LayoutDocument, LayoutSheet, SheetCell


def inspect_xlsx_safety(path: Path | PathLike[str] | BinaryIO) -> list[str]:
    """Return a list of unsafe features found (empty = safe)."""
    found = []
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except zipfile.BadZipFile as exc:
        raise CorruptFile() from exc
    if any(n.startswith("xl/vbaProject") for n in names):
        found.append("vba_macros")
    if any(n.startswith("xl/externalLinks/") for n in names):
        found.append("external_links")
    if any(
        n.startswith("xl/embeddings/") or n.startswith("xl/media/") and n.endswith((".exe", ".bin"))
        for n in names
    ):
        found.append("embedded_objects")
    return found


def excel_layout(path: Path, *, document_id: str, source_format: str) -> LayoutDocument:
    if source_format == "xlsx":
        unsafe = inspect_xlsx_safety(path)
        if unsafe:
            raise UnsafeWorkbook(errors={"unsafe_features": unsafe})
        return _xlsx(path, document_id)
    if source_format == "xls":
        return _xls(path, document_id)
    raise ValueError(source_format)


def _col_letter(idx: int) -> str:
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def _xlsx(path: Path, document_id: str) -> LayoutDocument:
    from openpyxl import load_workbook

    try:
        wb_v = load_workbook(path, read_only=True, data_only=True)  # cached values
        wb_f = load_workbook(path, read_only=False, data_only=False)  # formulas + merges
    except Exception as exc:
        raise CorruptFile() from exc
    sheets: list[LayoutSheet] = []
    for si, name in enumerate(wb_v.sheetnames):
        ws_v, ws_f = wb_v[name], wb_f[name]
        merged = [str(r) for r in ws_f.merged_cells.ranges]
        merged_lookup = {}
        for rng in ws_f.merged_cells.ranges:
            for merged_row in ws_f.iter_rows(
                min_row=rng.min_row, max_row=rng.max_row, min_col=rng.min_col, max_col=rng.max_col
            ):
                for c in merged_row:
                    merged_lookup[c.coordinate] = str(rng)
        cells, order, rows = [], [], []
        max_r, max_c = 0, 0
        for r_idx, value_row in enumerate(ws_v.iter_rows(values_only=True)):
            row_texts = []
            for c_idx, val in enumerate(value_row):
                if val is None:
                    continue
                ref = f"{_col_letter(c_idx)}{r_idx + 1}"
                fcell = ws_f[ref]
                formula = (
                    fcell.value
                    if isinstance(fcell.value, str) and fcell.value.startswith("=")
                    else None
                )
                cid = f"s{si}:{ref}"
                cells.append(
                    SheetCell(
                        id=cid,
                        ref=ref,
                        row=r_idx,
                        col=c_idx,
                        value=str(val),
                        formula=formula,
                        merged_range=merged_lookup.get(ref),
                        number_format=fcell.number_format,
                    )
                )
                order.append(cid)
                row_texts.append(f"{ref}={val}")
                max_r, max_c = max(max_r, r_idx + 1), max(max_c, c_idx + 1)
            if row_texts:
                rows.append(" | ".join(row_texts))
        sheets.append(
            LayoutSheet(
                index=si,
                name=name,
                row_count=max_r,
                col_count=max_c,
                cells=cells,
                merged_ranges=merged,
                tables=list(getattr(ws_f, "tables", {}).keys()),
                reading_order=order,
                content="\n".join(rows),
            )
        )
    return LayoutDocument(
        document_id=document_id,
        source_format="xlsx",
        service="openpyxl",
        service_version=_ver("openpyxl"),
        units=sheets,
    )


def _xls(path: Path, document_id: str) -> LayoutDocument:
    import xlrd

    try:
        book = xlrd.open_workbook(str(path), formatting_info=False)
    except Exception as exc:
        raise CorruptFile() from exc
    sheets: list[LayoutSheet] = []
    for si in range(book.nsheets):
        sh = book.sheet_by_index(si)
        cells, order, rows = [], [], []
        for r in range(sh.nrows):
            row_texts = []
            for c in range(sh.ncols):
                v = sh.cell_value(r, c)
                if v in ("", None):
                    continue
                ref = f"{_col_letter(c)}{r + 1}"
                cid = f"s{si}:{ref}"
                cells.append(SheetCell(id=cid, ref=ref, row=r, col=c, value=str(v)))
                order.append(cid)
                row_texts.append(f"{ref}={v}")
            if row_texts:
                rows.append(" | ".join(row_texts))
        merged = [
            f"{_col_letter(c0)}{r0 + 1}:{_col_letter(c1 - 1)}{r1}"
            for r0, r1, c0, c1 in sh.merged_cells
        ]
        sheets.append(
            LayoutSheet(
                index=si,
                name=sh.name,
                row_count=sh.nrows,
                col_count=sh.ncols,
                cells=cells,
                merged_ranges=merged,
                reading_order=order,
                content="\n".join(rows),
            )
        )
    return LayoutDocument(
        document_id=document_id,
        source_format="xls",
        service="xlrd",
        service_version=_ver("xlrd"),
        units=sheets,
    )


def _ver(mod):
    import importlib

    return getattr(importlib.import_module(mod), "__version__", "")
