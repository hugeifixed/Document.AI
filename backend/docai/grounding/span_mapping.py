"""Reconcile a PDF.js text selection with normalized layout words.

PDF.js gives: page number, selected text, and rects in PDF user space
(points, origin bottom-left). Layout words carry polygons normalized 0-1 with
origin top-left. Both are normalized here and matched by text (exact → fuzzy)
with geometry IoU as a tie-breaker; the method, score, and exceptions are
returned so labels store BOTH spans and the reviewer can see how good the
mapping is. Image-only pages (no PDF.js text layer) must select from the
layout's own word boxes; that path is `map_word_ids`."""

from __future__ import annotations

from rapidfuzz import fuzz

from docai.schemas.layout import LayoutPage

from .locate import _union, locate_in_page


def normalize_pdfjs_rects(
    rects: list[dict], page_w_pt: float, page_h_pt: float
) -> list[list[float]]:
    """rects: [{x, y, width, height}] in PDF points, origin bottom-left → normalized top-left boxes."""
    out = []
    for r in rects:
        x0 = r["x"] / page_w_pt
        x1 = (r["x"] + r["width"]) / page_w_pt
        y_top = 1 - ((r["y"] + r["height"]) / page_h_pt)
        y_bot = 1 - (r["y"] / page_h_pt)
        out.append([round(x0, 5), round(y_top, 5), round(x1, 5), round(y_bot, 5)])
    return out


def _bbox(poly):
    xs, ys = poly[0::2], poly[1::2]
    return [min(xs), min(ys), max(xs), max(ys)] if xs else None


def _iou(a, b):
    ix0, iy0, ix1, iy1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def map_pdfjs_selection(page: LayoutPage, text: str, rects_norm: list[list[float]]) -> dict:
    """Returns {word_ids, polygon, offset_start, offset_end, method, score, exceptions}."""
    exceptions = []
    hit = locate_in_page(text, page)
    if hit and hit["word_ids"]:
        # geometry check: does the union box overlap the selection?
        ub = _bbox(hit["polygon"])
        geo = max((_iou(ub, r) for r in rects_norm), default=0.0) if ub and rects_norm else 0.0
        if rects_norm and geo < 0.05:
            exceptions.append(
                f"text matched ({hit['method']}) but geometry overlap low ({geo:.2f}); "
                "possible repeated text on page"
            )
            # try geometry-first: words inside the selection rects
            inside = [
                w
                for w in page.words
                if w.polygon and any(_iou(_bbox(w.polygon), r) > 0.3 for r in rects_norm)
            ]
            if inside:
                cand = " ".join(w.text for w in inside)
                if fuzz.ratio(cand.lower(), text.lower()) >= 80:
                    return {
                        "word_ids": [w.id for w in inside],
                        "polygon": _union(inside),
                        "offset_start": inside[0].span.offset if inside[0].span else None,
                        "offset_end": (inside[-1].span.offset + inside[-1].span.length)
                        if inside[-1].span
                        else None,
                        "method": "geometry+text",
                        "score": 0.9,
                        "exceptions": exceptions,
                    }
        return {
            **hit,
            "exceptions": exceptions,
            "method": hit["method"] + ("+geometry" if geo >= 0.05 else ""),
        }
    if hit:
        exceptions.append("matched by text span only; no word boxes available")
        return {**hit, "exceptions": exceptions}
    # geometry only
    inside = [
        w
        for w in page.words
        if w.polygon and any(_iou(_bbox(w.polygon), r) > 0.3 for r in rects_norm)
    ]
    if inside:
        exceptions.append("text not found; mapped by geometry only")
        return {
            "word_ids": [w.id for w in inside],
            "polygon": _union(inside),
            "offset_start": None,
            "offset_end": None,
            "method": "geometry",
            "score": 0.6,
            "exceptions": exceptions,
        }
    return {
        "word_ids": [],
        "polygon": [],
        "offset_start": None,
        "offset_end": None,
        "method": "none",
        "score": 0.0,
        "exceptions": exceptions + ["no mapping found"],
    }


def map_word_ids(page: LayoutPage, word_ids: list[str]) -> dict:
    """Image-only pages: the UI selects layout word boxes directly."""
    words = [w for w in page.words if w.id in set(word_ids)]
    if not words:
        return {
            "word_ids": [],
            "polygon": [],
            "method": "none",
            "score": 0.0,
            "exceptions": ["unknown word ids"],
        }
    spans = [w.span for w in words if w.span]
    return {
        "word_ids": [w.id for w in words],
        "polygon": _union(words),
        "method": "word_boxes",
        "score": 1.0,
        "offset_start": spans[0].offset if spans else None,
        "offset_end": (spans[-1].offset + spans[-1].length) if spans else None,
        "text": " ".join(w.text for w in words),
        "exceptions": [],
    }
