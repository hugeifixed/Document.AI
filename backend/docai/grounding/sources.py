"""Validate model citations against original unit indexes and stable layout ids."""

from __future__ import annotations

import re
from typing import Any

from docai.exceptions import InvalidModelOutput
from docai.schemas.layout import (
    LayoutDocument,
    LayoutPage,
    LayoutSheet,
    SelectionMark,
    Table,
    TableCell,
)
from docai.schemas.llm import SourceRef


def source_elements(unit: LayoutPage | LayoutSheet) -> dict[str, Any]:
    if isinstance(unit, LayoutSheet):
        return {cell.id: cell for cell in unit.cells}
    elements: list[Any] = [
        *unit.words,
        *unit.lines,
        *unit.paragraphs,
        *unit.tables,
        *(cell for table in unit.tables for cell in table.cells),
        *unit.selection_marks,
    ]
    return {element.id: element for element in elements}


def validate_sources(
    layout: LayoutDocument,
    sources: list[SourceRef],
    *,
    unit_index: int | None = None,
    allowed_indexes: set[int] | None = None,
    allowed_ids: dict[int, set[str]] | None = None,
) -> None:
    units = {
        unit.index: unit
        for unit in layout.units
        if not (isinstance(unit, LayoutPage) and unit.excluded_from_analysis)
        and (allowed_indexes is None or unit.index in allowed_indexes)
    }
    if unit_index is not None and unit_index not in units:
        raise InvalidModelOutput(
            errors={"unit_index": "Must identify an original submitted unit."},
            diagnostics={"unit_index": unit_index, "validation_reason": "unknown_unit"},
        )
    if sources and unit_index is not None and unit_index not in {s.unit_index for s in sources}:
        raise InvalidModelOutput(
            errors={"sources": "Field and source unit indexes disagree."},
            diagnostics={"unit_index": unit_index, "validation_reason": "source_unit_mismatch"},
        )
    for source in sources:
        unit = units.get(source.unit_index)
        if (
            unit is None
            or not set(source.ids).issubset(source_elements(unit))
            or (
                allowed_ids is not None
                and not set(source.ids).issubset(allowed_ids.get(source.unit_index, set()))
            )
        ):
            raise InvalidModelOutput(
                errors={"sources": "Source indexes and ids must identify the same submitted unit."},
                diagnostics={
                    "unit_index": source.unit_index,
                    "validation_reason": "unknown_source",
                },
            )


def submitted_sources(
    layout: LayoutDocument, text: str, allowed_indexes: set[int]
) -> tuple[LayoutDocument, dict[int, set[str]]]:
    """Capture complete source elements visible in this exact rendered chunk.

    A page index does not identify a chunk when a page is split. A table header
    alone also cannot expose the table's unseen cells, and a trailing paragraph
    marker cannot expose text cut off at the start of the chunk.
    """
    visible: dict[str, list[tuple[str, str]]] = {}
    previous_end = 0
    for marker in re.finditer(r"\[[^\]\n]+\]", text):
        marker_ids = re.findall(r"(?<!\w)p[0-9]+:[a-z]+[0-9]+(?::[a-z]+[0-9]+)*", marker[0])
        if marker_ids:
            for source_id in marker_ids:
                visible.setdefault(source_id, []).append(
                    (text[previous_end : marker.start()], marker[0])
                )
            previous_end = marker.end()

    def normalized(value: str) -> str:
        return " ".join(value.replace("\\|", "|").split())

    ids_by_unit: dict[int, set[str]] = {}
    units: list[LayoutPage | LayoutSheet] = []
    for unit in layout.units:
        if unit.index not in allowed_indexes:
            continue
        if isinstance(unit, LayoutSheet):
            # Spreadsheet rendering uses A1=value, under an original unit header.
            blocks = re.split(r"(?m)(?=^===)", text)
            unit_text = "\n".join(
                block
                for block in blocks
                if re.search(rf"\(unit {unit.index},", block.partition("\n")[0])
            )
            ids = {
                cell.id
                for cell in unit.cells
                if re.search(
                    rf"(?<!\w){re.escape(cell.ref)}={re.escape(cell.value or '')}(?=\s*(?:\(=|\||\n|$))",
                    unit_text,
                )
            }
            units.append(
                unit.model_copy(
                    update={"cells": [c for c in unit.cells if c.id in ids], "content": ""}
                )
            )
        else:
            elements = source_elements(unit)
            ids = set()
            if not unit.excluded_from_analysis:
                for source_id in visible.keys() & elements.keys():
                    element = elements[source_id]
                    if isinstance(element, Table):
                        continue  # A table is available only after all its cells are verified.
                    elif isinstance(element, SelectionMark):
                        complete = any(
                            marker == f"[checkbox {element.id}: {element.state}]"
                            for _prefix, marker in visible[source_id]
                        )
                    else:
                        prefixes = [prefix for prefix, _marker in visible[source_id]]
                        if isinstance(element, TableCell):
                            prefixes = [re.split(r"(?<!\\)\|", prefix)[-1] for prefix in prefixes]
                        complete = any(
                            normalized(element.text) in normalized(prefix) for prefix in prefixes
                        )
                    if complete:
                        ids.add(source_id)
                ids.update(
                    table.id
                    for table in unit.tables
                    if table.id in visible and all(cell.id in ids for cell in table.cells)
                )
            cited = cited_unit(unit, ids) if ids else unit.model_copy(update={"words": []})
            units.append(
                cited.model_copy(
                    update={
                        "content": "",
                        "selection_marks": [
                            mark for mark in unit.selection_marks if mark.id in ids
                        ],
                    }
                )
            )
        ids_by_unit[unit.index] = ids
    return layout.model_copy(update={"units": units}), ids_by_unit


def cited_unit(unit: LayoutPage | LayoutSheet, ids: set[str]) -> LayoutPage | LayoutSheet:
    """Restrict a value search to cited evidence, retaining original ids and offsets.

    A line/paragraph/table reference can cover several words. Resolve its explicit
    word ids or character spans; unavailable geometry remains ungrounded.
    """
    if not ids:
        return unit
    if isinstance(unit, LayoutSheet):
        return unit.model_copy(update={"cells": [cell for cell in unit.cells if cell.id in ids]})
    elements = source_elements(unit)
    selected = [elements[source_id] for source_id in ids]
    selected = [cell for element in selected for cell in getattr(element, "cells", [element])]
    word_ids = ids | {
        word_id for element in selected for word_id in getattr(element, "word_ids", [])
    }
    spans = [element.span for element in selected if getattr(element, "span", None)]
    words = [
        word
        for word in unit.words
        if word.id in word_ids
        or (
            word.span is not None
            and any(
                span.offset <= word.span.offset
                and word.span.offset + word.span.length <= span.offset + span.length
                for span in spans
            )
        )
    ]
    return unit.model_copy(update={"words": words, "content": ""})
