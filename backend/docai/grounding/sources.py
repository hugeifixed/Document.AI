"""Validate model citations against original unit indexes and stable layout ids."""

from __future__ import annotations

from typing import Any

from docai.exceptions import InvalidModelOutput
from docai.schemas.layout import LayoutDocument, LayoutPage, LayoutSheet
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
) -> None:
    units = {
        unit.index: unit
        for unit in layout.units
        if not (isinstance(unit, LayoutPage) and unit.excluded_from_analysis)
        and (allowed_indexes is None or unit.index in allowed_indexes)
    }
    if unit_index is not None and unit_index not in units:
        raise InvalidModelOutput(errors={"unit_index": "Must identify an original submitted unit."})
    if sources and unit_index is not None and unit_index not in {s.unit_index for s in sources}:
        raise InvalidModelOutput(errors={"sources": "Field and source unit indexes disagree."})
    for source in sources:
        unit = units.get(source.unit_index)
        if unit is None or not set(source.ids).issubset(source_elements(unit)):
            raise InvalidModelOutput(
                errors={"sources": "Source indexes and ids must identify the same submitted unit."}
            )


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
