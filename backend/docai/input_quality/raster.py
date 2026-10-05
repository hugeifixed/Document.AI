"""Bounded metadata decoding shared by base preparation and optional enhancement."""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageOps

from docai.exceptions import NormalizationLimitExceeded


def check_size(width: int, height: int, *, max_pixels: int, max_dimension: int) -> None:
    if min(width, height) <= 0 or max(width, height) > max_dimension or width * height > max_pixels:
        raise NormalizationLimitExceeded()


def prepare_raster(
    original: Image.Image, *, max_pixels: int, max_dimension: int
) -> tuple[Image.Image, dict[str, Any]]:
    """Own an RGB copy with metadata orientation consumed exactly once, preserving tones."""
    check_size(*original.size, max_pixels=max_pixels, max_dimension=max_dimension)
    orientation = original.getexif().get(274, 1)
    oriented = ImageOps.exif_transpose(original)
    operations = ["exif_orientation"] if orientation in range(2, 9) else []
    try:
        if oriented.mode in {"RGBA", "LA"} or "transparency" in oriented.info:
            with oriented.convert("RGBA") as rgba:
                image = Image.new("RGB", rgba.size, "white")
                image.paste(rgba, mask=rgba.getchannel("A"))
            operations.append("color_mode")
        else:
            image = oriented.convert("RGB")
            if oriented.mode != "RGB":
                operations.append("color_mode")
    finally:
        oriented.close()
    return image, {
        "operations": operations,
        "original_width": original.width,
        "original_height": original.height,
        "original_unit": "pixel",
        "exif_orientation": int(orientation),
        "has_text_layer": False,
        "status": "adjusted" if operations else "unchanged",
        "width": image.width,
        "height": image.height,
        "unit": "pixel",
    }
