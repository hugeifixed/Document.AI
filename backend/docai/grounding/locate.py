"""Locate an extracted value in a unit's layout: exact word-sequence, digit
stream (identifiers/amounts across punctuation), then fuzzy sliding window.
Ported from the prototype; polygons are normalized 0-1 so the output feeds
PDF.js overlays directly. Returns word ids + union polygon + text span."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from docai.schemas.layout import LayoutPage, LayoutSheet, Word

FUZZ_THRESHOLD = 86


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _union(words: list[Word]) -> list[float]:
    xs = [v for w in words for v in w.polygon[0::2]]
    ys = [v for w in words for v in w.polygon[1::2]]
    if not xs:
        return []
    return [min(xs), min(ys), max(xs), min(ys), max(xs), max(ys), min(xs), max(ys)]


def locate_in_page(value: str, page: LayoutPage, evidence: str | None = None) -> dict | None:
    if not value or not page.words:
        return None
    toks = [t for t in re.split(r"\s+", value.strip()) if t]
    words = page.words
    n = len(toks)
    norm = lambda s: re.sub(r"[^\w]", "", s).lower()  # noqa: E731

    # 1) exact token run
    for i in range(0, len(words) - n + 1):
        if all(norm(words[i + k].text) == norm(toks[k]) for k in range(n)):
            return _hit(words[i : i + n], "exact", 1.0)
    # 2) digit stream for identifier-like values
    vd = _digits(value)
    if len(vd) >= 4:
        for i in range(len(words)):
            acc, j = "", i
            while j < len(words) and len(acc) < len(vd):
                acc += _digits(words[j].text)
                j += 1
                if acc == vd:
                    return _hit(words[i:j], "digits", 0.97)
                if not vd.startswith(acc):
                    break
    # 3) fuzzy sliding window (n-1..n+1)
    best, best_score = None, 0
    for width in (max(1, n - 1), n, n + 1):
        for i in range(0, len(words) - width + 1):
            cand = " ".join(w.text for w in words[i : i + width])
            s = fuzz.ratio(cand.lower(), value.lower())
            if s > best_score:
                best, best_score = words[i : i + width], s
    if best and best_score >= FUZZ_THRESHOLD:
        return _hit(best, "fuzzy", round(best_score / 100, 3))
    # 4) text-span fallback (no boxes)
    pos = page.content.lower().find(value.lower())
    if pos >= 0:
        return {
            "word_ids": [],
            "polygon": [],
            "offset_start": pos,
            "offset_end": pos + len(value),
            "method": "text_span",
            "score": 0.8,
        }
    return None


def _hit(words: list[Word], method: str, score: float) -> dict:
    spans = [w.span for w in words if w.span]
    return {
        "word_ids": [w.id for w in words],
        "polygon": _union(words),
        "method": method,
        "score": score,
        "offset_start": spans[0].offset if spans else None,
        "offset_end": (spans[-1].offset + spans[-1].length) if spans else None,
    }


def locate_in_sheet(value: str, sheet: LayoutSheet) -> dict | None:
    if not value:
        return None
    v = value.strip().lower()
    vd = _digits(value)
    for c in sheet.cells:
        cv = (c.value or "").strip().lower()
        if cv == v or (len(vd) >= 4 and _digits(c.value or "") == vd):
            return {"word_ids": [c.id], "cell_range": c.ref, "method": "exact", "score": 1.0}
    for c in sheet.cells:
        if v and v in (c.value or "").lower():
            return {"word_ids": [c.id], "cell_range": c.ref, "method": "contains", "score": 0.9}
    return None
