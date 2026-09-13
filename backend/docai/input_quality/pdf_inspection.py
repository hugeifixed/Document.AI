"""Inspect PDF page content with core pypdf only; never decode raster pixels."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pypdf import PageObject, PdfReader
from pypdf.generic import DictionaryObject


def native_text(page: PageObject) -> tuple[bool, bool]:
    """A page-sized scan with OCR text does not have a native digital text layer.

    Keep ambiguous pages unchanged. Visible native text pages are copied as PDF objects,
    retaining vector content; invisible OCR text alone never triggers the digital bypass.
    """
    visible_text = False
    text_present = False
    render_mode = 0
    dominant_image = False
    modes: list[int] = []
    resources = (
        cast(DictionaryObject, page["/Resources"]) if "/Resources" in page else DictionaryObject()
    )
    xobjects = (
        cast(DictionaryObject, resources["/XObject"])
        if "/XObject" in resources
        else DictionaryObject()
    )
    area = float(page.mediabox.width) * float(page.mediabox.height)

    def operand(operator, operands, cm, tm):
        nonlocal render_mode, dominant_image
        if operator == b"q":
            modes.append(render_mode)
        elif operator == b"Q" and modes:
            render_mode = modes.pop()
        elif operator == b"Tr":
            render_mode = int(operands[0])
        elif operator == b"Do":
            obj = xobjects.get(operands[0])
            if obj is not None and obj.get_object().get("/Subtype") == "/Image":
                image_area = abs(float(cm[0]) * float(cm[3]) - float(cm[1]) * float(cm[2]))
                dominant_image |= image_area >= area * 0.7

    def text(value, cm, tm, font, size):
        nonlocal visible_text, text_present
        if (value or "").strip():
            text_present = True
            visible_text |= render_mode not in {3, 7}

    page.extract_text(visitor_text=text, visitor_operand_before=operand)
    return visible_text and not dominant_image, text_present


def page_detail(page: PageObject, number: int) -> dict[str, Any]:
    native, has_text = native_text(page)
    # keys() inspects resource identifiers without decoding embedded image pixels.
    has_raster = bool(page.images.keys())
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    if int(page.get("/Rotate", 0)) % 180:
        width, height = height, width
    return {
        "page": number,
        "status": "bypassed" if native or not has_raster else "unchanged",
        "operations": [],
        "width": width,
        "height": height,
        "unit": "point",
        "has_text_layer": native,
        "has_existing_text": has_text,
        "has_raster_content": has_raster,
    }


def text_layers(path: Path) -> dict[int, bool]:
    """Prove native selectable text per original page; unknown pages stay false."""
    layers: dict[int, bool] = {}
    try:
        with path.open("rb") as stream:
            reader = PdfReader(stream)
            for index, page in enumerate(reader.pages):
                try:
                    layers[index] = native_text(page)[0]
                except Exception:  # noqa: BLE001 — inspection cannot turn unknown text into native text
                    layers[index] = False
    except Exception:  # noqa: BLE001 — layout/OCR can still handle inputs pypdf cannot inspect
        return {}
    return layers
