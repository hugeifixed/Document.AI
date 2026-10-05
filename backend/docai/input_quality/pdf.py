"""PDF inspection, serialized native rendering and lossless raster PDF pages."""

from __future__ import annotations

import math
import threading
from pathlib import Path

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from docai.exceptions import NormalizationLimitExceeded

PDFIUM_LOCK = threading.Lock()


def render_page(
    path: Path, index: int, *, max_pixels: int, max_dimension: int, allow_downscale: bool = False
) -> tuple[Image.Image, float]:
    import pypdfium2 as pdfium

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
            if scale < 1 and not allow_downscale:
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
