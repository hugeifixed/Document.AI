"""PDF inspection, serialized native rendering and lossless raster PDF pages."""

from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Any, cast

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PageObject, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from docai.exceptions import NormalizationLimitExceeded

PDFIUM_LOCK = threading.Lock()


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


def render_page(
    path: Path, index: int, *, max_pixels: int, max_dimension: int
) -> tuple[Image.Image, float]:
    # Include constructors, to_pil copying, and *all* cleanup in the process-wide mutex.
    # Never let a bitmap-backed PIL image or an open PDFium object escape this block.
    with PDFIUM_LOCK, pdfium.PdfDocument(str(path)) as document:
        page = document[index]
        try:
            width, height = page.get_size()
            if min(width, height) <= 0:
                raise NormalizationLimitExceeded()
            scale = min(
                300 / 72,
                math.sqrt(max_pixels / (width * height)),
                max_dimension / max(width, height),
            )
            if scale < 1:
                raise NormalizationLimitExceeded()
            # Round-down margin avoids ceil-to-pixel dimensions exceeding the cap.
            scale *= 0.999
            bitmap = page.render(scale=scale)
            try:
                pil = bitmap.to_pil()
                try:
                    return pil.copy(), scale * 72
                finally:
                    pil.close()
            finally:
                bitmap.close()
        finally:
            page.close()


def write_image_pdf(image: Image.Image, path: Path, *, dpi: float) -> None:
    """Embed RGB pixels with Flate compression instead of introducing JPEG loss."""
    writer = PdfWriter()
    try:
        width, height = image.width * 72 / dpi, image.height * 72 / dpi
        page = writer.add_blank_page(width=width, height=height)
        pixels = DecodedStreamObject()
        pixels.set_data(image.tobytes())
        pixels.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(image.width),
                NameObject("/Height"): NumberObject(image.height),
                NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                NameObject("/BitsPerComponent"): NumberObject(8),
            }
        )
        # PDF stream objects must be indirect, including nested image resources.
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/XObject"): DictionaryObject(
                    {NameObject("/Scan"): writer._add_object(pixels.flate_encode())}
                ),
                NameObject("/ProcSet"): ArrayObject([NameObject("/PDF"), NameObject("/ImageC")]),
            }
        )
        content = DecodedStreamObject()
        content.set_data(f"q {width:.6f} 0 0 {height:.6f} 0 0 cm /Scan Do Q".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)
        writer.write(str(path))
    finally:
        writer.close()


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
