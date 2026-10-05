"""Conservative identity for generic predictions of the same source occurrence.

A displayed label (or label and value) does not identify a record. Only an
explicit, unambiguous verified source can authorize removal of a prediction.
Ordinary grounding may choose a first match or allow fuzzy matches; neither is
enough to prove that two candidates describe one occurrence.
"""

from __future__ import annotations

import re

from docai.grounding.locate import locate_in_page
from docai.grounding.properties import verified_location
from docai.grounding.sources import cited_unit
from docai.schemas.layout import LayoutDocument, LayoutPage
from docai.schemas.llm import FieldOut

from .evidence import EvidenceDecision


class AutoOccurrences:
    """Retain the first independently verified prediction of each occurrence."""

    def __init__(self, layout: LayoutDocument):
        self._layout = layout
        self._seen: set[tuple[str, str, int, tuple[str, ...]]] = set()

    def is_repeat(
        self,
        field: FieldOut,
        decision: EvidenceDecision,
        allowed_indexes: set[int],
        submitted_layout: LayoutDocument,
    ) -> bool:
        if field.value is None or field.value == "" or decision.grounding is None:
            return False
        if decision.grounding.get("method") not in {"exact", "digits", "selection_mark"}:
            return False
        hit, _status = verified_location(self._layout, field, allowed_indexes)
        if hit is None:
            return False
        ids = set(hit["word_ids"])
        if hit["unit_index"] != decision.grounding.get("unit_index") or ids != set(
            decision.grounding.get("word_ids", [])
        ):
            return False
        visible: set[str] = set()
        for unit in submitted_layout.units:
            if unit.index != hit["unit_index"]:
                continue
            if isinstance(unit, LayoutPage):
                visible.update(word.id for word in unit.words)
                visible.update(mark.id for mark in unit.selection_marks)
            else:
                visible.update(cell.id for cell in unit.cells)
        # A source unit can span multiple chunks. An unavailable occurrence must
        # not suppress a submitted neighbor, even when both cite the same unit.
        if not ids or not ids.issubset(visible):
            return False
        if hit["method"] == "digits" and any(
            page.index == hit["unit_index"] for page in self._layout.pages
        ):
            # Digit matching can include preceding label words that contribute
            # no digits. Their presence depends on the citation's width, not the
            # value's physical occurrence. Canonicalize only those boundaries.
            words = {
                word.id: word
                for page in self._layout.pages
                if page.index == hit["unit_index"]
                for word in page.words
            }
            matched = list(hit["word_ids"])
            while matched and not re.search(r"\d", words[matched[0]].text):
                matched.pop(0)
            while matched and not re.search(r"\d", words[matched[-1]].text):
                matched.pop()
            ids = set(matched)
        if _overlapping_match(self._layout, field, hit["unit_index"], ids):
            return False
        key = (
            " ".join(field.name.split()).casefold(),
            field.value,
            hit["unit_index"],
            tuple(sorted(ids)),
        )
        if key in self._seen:
            return True
        self._seen.add(key)
        return False


def _overlapping_match(
    layout: LayoutDocument, field: FieldOut, index: int, matched_ids: set[str]
) -> bool:
    """A second occurrence can share words with the verifier's first match.

    Removing all matched words at once misses a phrase like ``A A`` in ``A A A``.
    Removing one matched word at a time conservatively catches such alternatives.
    """
    if len(matched_ids) < 2:
        return False
    page = next((page for page in layout.pages if page.index == index), None)
    if page is None or not set(matched_ids).issubset(word.id for word in page.words):
        return False
    sources = {id_ for source in field.sources if source.unit_index == index for id_ in source.ids}
    cited = cited_unit(page, sources)
    if not isinstance(cited, LayoutPage):
        return False
    for word_id in matched_ids:
        remaining = cited.model_copy(update={"words": [w for w in cited.words if w.id != word_id]})
        alternative = locate_in_page(field.value or "", remaining)
        if alternative and alternative["method"] in {"exact", "digits"}:
            return True
    return False
