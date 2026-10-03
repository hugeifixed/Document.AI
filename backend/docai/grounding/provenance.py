"""Interpret source evidence consistently from extraction through human promotion.

Mapping methods describe how a location was found. Property identity and citation
correction are separate provenance, stored in the existing exceptions metadata.
Legacy prefixed methods remain readable; new writes fit the 32-character columns.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from docai.validation.collections import parse_list

if TYPE_CHECKING:
    from docai.models import SourceSpan
    from docai.workflows.base import FieldResultData

_PATH = "list_property_path="
_REPAIR = "citation_repair"
_METHOD = "mapping_method="
_METHOD_LIMIT = 32


@dataclass(frozen=True)
class SpanProvenance:
    method: str = ""
    property_path: str | None = None
    citation_repaired: bool = False
    exceptions: tuple[Any, ...] = ()

    @classmethod
    def from_grounding(
        cls, hit: dict, *, path: str | None = None, repaired: bool = False
    ) -> SpanProvenance:
        return cls._decode(
            hit.get("method", ""),
            hit.get("exceptions", []),
            path=path,
            repaired=repaired or bool(hit.get("citation_repaired")),
        )

    @classmethod
    def from_span(cls, span: SourceSpan) -> SpanProvenance:
        return cls._decode(span.mapping_method, span.exceptions)

    @classmethod
    def _decode(
        cls,
        method: str,
        exceptions: Iterable[Any],
        *,
        path: str | None = None,
        repaired: bool = False,
    ) -> SpanProvenance:
        notes = []
        for note in exceptions:
            if isinstance(note, str) and note.startswith(_PATH):
                path = note[len(_PATH) :]
            elif note == _REPAIR:
                repaired = True
            elif isinstance(note, str) and note.startswith(_METHOD):
                method = note[len(_METHOD) :]
            else:
                notes.append(note)
        while method.startswith(("citation_repair:", "list_property:")):
            prefix, method = method.split(":", 1)
            repaired = repaired or prefix == "citation_repair"
            if prefix == "list_property" and path is None:
                path = ""  # Legacy property evidence without a usable pointer.
        return cls(method, path, repaired, tuple(notes))

    def metadata(self, *, promoted: bool = False) -> dict:
        suffix = "+promoted" if promoted else ""
        method = self.method[: _METHOD_LIMIT - len(suffix)] + suffix
        notes = list(self.exceptions)
        if self.property_path is not None:
            notes.append(_PATH + self.property_path)
        if self.citation_repaired:
            notes.append(_REPAIR)
        if len(self.method) > _METHOD_LIMIT - len(suffix):
            notes.append(_METHOD + self.method)
        return {"mapping_method": method, "exceptions": notes}


def has_box(hit: dict | None) -> bool:
    polygon = (hit or {}).get("polygon") or []
    return (
        len(polygon) >= 6
        and len(polygon) % 2 == 0
        and all(math.isfinite(n) and 0 <= n <= 1 for n in polygon)
        and min(polygon[::2]) < max(polygon[::2])
        and min(polygon[1::2]) < max(polygon[1::2])
    )


@dataclass(frozen=True)
class FieldLocation:
    value: Any
    status: str
    grounding: dict | None
    sources: list[dict]
    provenance: SpanProvenance

    @property
    def unit_index(self) -> int | None:
        if self.grounding:
            index = self.grounding.get("unit_index")
            return index if isinstance(index, int) else None
        indexes: set[int] = {source["unit_index"] for source in self.sources}
        return next(iter(indexes)) if len(indexes) == 1 else None

    @property
    def boxed(self) -> bool:
        return self.status == "grounded" and has_box(self.grounding)

    @property
    def display_unit_index(self) -> int | None:
        if self.boxed:
            return self.unit_index
        indexes: set[int] = {source["unit_index"] for source in self.sources}
        return next(iter(indexes)) if len(indexes) == 1 else None

    def span_values(self) -> dict | None:
        hit = self.grounding
        if self.status != "grounded" or not hit:
            return None
        return {
            "text": str(self.value)[:500],
            "offset_start": hit.get("offset_start"),
            "offset_end": hit.get("offset_end"),
            "polygon": hit.get("polygon", []),
            "word_ids": hit.get("word_ids", []),
            "cell_range": hit.get("cell_range", "") or "",
            "match_score": hit.get("score"),
            **self.provenance.metadata(),
        }


def field_locations(field: FieldResultData) -> list[FieldLocation]:
    """Expose scalar or property locations; a list never has an aggregate location."""
    if field.raw_value in (None, ""):
        return []
    if field.field_type == "list":
        if field.property_evidence:
            return [
                FieldLocation(
                    prop["value"],
                    prop["status"],
                    prop.get("grounding") if prop["status"] == "grounded" else None,
                    prop["sources"],
                    SpanProvenance.from_grounding(
                        prop.get("grounding") or {},
                        path=prop["path"],
                        repaired=prop.get("citation_repaired", False),
                    ),
                )
                for prop in field.property_evidence
                if prop["value"] is not None and prop["status"] != "invalid_path"
            ]
        try:
            if not parse_list(field.raw_value):
                return []
        except ValueError:
            pass
    hit = field.grounding if field.field_type != "list" else None
    sources = [
        source
        for candidate in field.candidates
        if candidate.get("value") == field.raw_value
        for source in candidate.get("sources", [])
    ]
    return [
        FieldLocation(
            field.raw_value,
            "grounded" if hit else "unverified",
            hit,
            sources,
            SpanProvenance.from_grounding(hit or {}),
        )
    ]


def promotion_source(field) -> SourceSpan | None:
    """A property span cannot represent an accepted or corrected aggregate list."""
    if field.field_type == "list":
        return None
    return next(
        (
            span
            for span in field.spans.select_related("unit").order_by("created", "id")
            if SpanProvenance.from_span(span).property_path is None
        ),
        None,
    )


def source_reference(obj) -> dict:
    """Export stored evidence with the same property and correction interpretation."""
    if not hasattr(obj, "spans"):
        return {}
    spans = obj.spans.select_related("unit").order_by("created", "id")
    if getattr(obj, "field_type", None) == "list":
        properties = []
        for span in spans:
            provenance = SpanProvenance.from_span(span)
            if provenance.property_path:
                properties.append(
                    {
                        "path": provenance.property_path,
                        **_span_reference(span),
                        "citation_repaired": provenance.citation_repaired,
                    }
                )
        return {"property_spans": properties} if properties else {}
    span = next(
        (span for span in spans if SpanProvenance.from_span(span).property_path is None), None
    )
    if span is None:
        return {}
    return {"unit_kind": span.unit.kind, **_span_reference(span)}


def _span_reference(span: SourceSpan) -> dict:
    return {
        "unit_index": span.unit.index,
        "layout_artifact": str(span.unit.layout_artifact_id)
        if span.unit.layout_artifact_id
        else None,
        "word_ids": span.word_ids,
        "polygon": span.polygon,
        "offset_start": span.offset_start,
        "offset_end": span.offset_end,
        "cell_range": span.cell_range,
        "mapping_method": span.mapping_method,
        "match_score": span.match_score,
        "citation_repaired": SpanProvenance.from_span(span).citation_repaired,
    }
