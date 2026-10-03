"""Verify individual list leaves against explicit, unambiguous cited locations."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from docai.exceptions import InvalidModelOutput
from docai.schemas.layout import LayoutDocument, LayoutPage
from docai.schemas.llm import FieldOut
from docai.validation.collections import parse_list

from .locate import locate_in_page, locate_in_sheet
from .provenance import has_box
from .selection_marks import ground_selection_mark
from .sources import cited_unit, validate_sources


def verified_location(
    layout: LayoutDocument, field: FieldOut, allowed_indexes: set[int]
) -> tuple[dict | None, str]:
    """No uncited search, fuzzy match, missing geometry, or repeated-value substitution."""
    if not field.sources or any(not source.ids for source in field.sources):
        return None, "missing_reference"
    try:
        validate_sources(
            layout, field.sources, unit_index=field.unit_index, allowed_indexes=allowed_indexes
        )
    except InvalidModelOutput:
        return None, "invalid_reference"
    claimed, mark = ground_selection_mark(
        layout, field, field.unit_index, allowed_indexes=allowed_indexes
    )
    if claimed:
        return (mark, "grounded") if mark else (None, "unverified_checkbox")
    hits = []
    for unit in layout.units:
        if unit.index not in allowed_indexes:
            continue
        ids = {
            id_ for source in field.sources if source.unit_index == unit.index for id_ in source.ids
        }
        if not ids:
            continue
        cited = cited_unit(unit, ids)
        hit = (
            locate_in_page(field.value or "", cited)
            if isinstance(cited, LayoutPage)
            else locate_in_sheet(field.value or "", cited)
        )
        if not hit or hit["method"] not in {"exact", "digits"}:
            continue
        remaining = (
            cited.model_copy(
                update={"words": [w for w in cited.words if w.id not in hit["word_ids"]]}
            )
            if isinstance(cited, LayoutPage)
            else cited.model_copy(
                update={"cells": [c for c in cited.cells if c.id not in hit["word_ids"]]}
            )
        )
        second = (
            locate_in_page(field.value or "", remaining)
            if isinstance(remaining, LayoutPage)
            else locate_in_sheet(field.value or "", remaining)
        )
        if second and second["method"] in {"exact", "digits"}:
            return None, "ambiguous_reference"
        if isinstance(cited, LayoutPage) and (
            not hit.get("polygon")
            or any(
                not has_box({"polygon": w.polygon}) for w in cited.words if w.id in hit["word_ids"]
            )
        ):
            return None, "missing_geometry"
        hits.append({"unit_index": unit.index, **hit})
    if len(hits) > 1:
        return None, "ambiguous_reference"
    return (hits[0], "grounded") if hits else (None, "value_not_found")


def _leaves(value: Any) -> list[tuple[str, tuple[str | None, ...], Any]]:
    out: list[tuple[str, tuple[str | None, ...], Any]] = []
    stack: list[tuple[str, tuple[str | None, ...], Any]] = [("", (), value)]
    while stack:
        path, family, item = stack.pop()
        if isinstance(item, dict):
            children = [
                (
                    f"{path}/{key.replace('~', '~0').replace('/', '~1')}",
                    (*family, key),
                    v,
                )
                for key, v in item.items()
            ]
            stack.extend(reversed(children))
        elif isinstance(item, list):
            stack.extend(
                reversed([(f"{path}/{i}", (*family, None), v) for i, v in enumerate(item)])
            )
        elif item is not None and item != "":
            out.append((path, family, item))
    return out


def ground_properties(
    layout: LayoutDocument, field: FieldOut, allowed_indexes: set[int]
) -> list[dict]:
    try:
        leaves = _leaves(parse_list(field.value or ""))
    except ValueError:
        return []
    references = {p.path: p for p in field.property_sources}
    counts = Counter(p.path for p in field.property_sources)
    evidence = []
    families = {path: family for path, family, _value in leaves}
    for path, _family, value in leaves:
        ref = references.get(path)
        hit, status = None, "missing_reference"
        if ref:
            if counts[path] > 1:
                status = "duplicate_path"
            else:
                text = value if isinstance(value, str) else json.dumps(value, allow_nan=False)
                if isinstance(value, bool) and any(
                    id_ in {mark.id for page in layout.pages for mark in page.selection_marks}
                    for source in ref.sources
                    for id_ in source.ids
                ):
                    text = "selected" if value else "unselected"
                candidate = FieldOut(name=path, value=text, sources=ref.sources)
                hit, status = verified_location(layout, candidate, allowed_indexes)
        evidence.append(
            {
                "path": path,
                "value": value,
                "status": status,
                "sources": [s.model_dump() for s in ref.sources] if ref else [],
                "grounding": hit,
            }
        )
    known_paths = set(families)
    for ref in field.property_sources:
        if ref.path not in known_paths:
            evidence.append(
                {
                    "path": ref.path,
                    "value": None,
                    "status": "invalid_path",
                    "sources": [s.model_dump() for s in ref.sources],
                    "grounding": None,
                }
            )
    # Two distinct records must not silently borrow the same physical occurrence.
    occurrences: dict[tuple, list[dict]] = {}
    for item in evidence:
        hit = item["grounding"]
        if hit:
            key = (families[item["path"]], hit["unit_index"], tuple(hit["word_ids"]))
            occurrences.setdefault(key, []).append(item)
    for items in occurrences.values():
        if len(items) > 1:
            for item in items:
                item.update(status="ambiguous_row", grounding=None)
    return evidence
