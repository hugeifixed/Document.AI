"""Conservative raster decisions. Imported only by the optional native processor."""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np
from PIL import Image

from .raster import check_size, prepare_raster


def is_blank(image: Image.Image) -> bool:
    """Keep faint signatures/checkboxes even when their area meets the blank threshold.

    Thresholds are intentionally conservative engineering heuristics, not calibrated
    probabilities. Only near-white uniform pages or a few isolated specks are omitted.
    """
    pixels = np.asarray(image)
    gray = pixels.min(axis=2) if pixels.ndim == 3 else pixels
    if float(np.count_nonzero(gray >= 250)) / gray.size < 0.9995:
        return False
    foreground = (gray < 253).astype(np.uint8)
    if int(foreground.sum()) > 16:
        return False
    _, _, stats, _ = cv2.connectedComponentsWithStats(foreground, connectivity=8)
    areas = stats[1:, cv2.CC_STAT_AREA]
    # An additional four-pixel ceiling protects sparse meaningful marks on large scans.
    return not len(areas) or int(areas.max()) <= min(4, gray.size * 0.0002)


def deskew_angle(gray: np.ndarray) -> tuple[float, float]:
    """Require several long, agreeing lines; confidence is line agreement only."""
    height, width = gray.shape
    scale = min(1.0, 1800 / max(width, height))
    sampled = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
    edges = cv2.Canny(sampled, 40, 120)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 720,
        threshold=60,
        minLineLength=max(60, sampled.shape[1] // 6),
        maxLineGap=12,
    )
    if lines is None:
        return 0.0, 0.0
    angles, lengths = [], []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        angle = math.degrees(math.atan2(int(y2) - int(y1), int(x2) - int(x1)))
        # Vertical form rules do not support a horizontal text-baseline estimate.
        if abs(angle) <= 12:
            angles.append(angle)
            lengths.append(math.hypot(int(x2) - int(x1), int(y2) - int(y1)))
    if len(angles) < 5:
        return 0.0, 0.0
    median = float(np.median(angles))
    agreeing = sum(
        length for angle, length in zip(angles, lengths, strict=True) if abs(angle - median) <= 0.5
    )
    confidence = agreeing / sum(lengths)
    return (
        (median, confidence) if 0.5 <= abs(median) <= 8 and confidence >= 0.9 else (0.0, confidence)
    )


def improve_image(
    original: Image.Image, *, max_pixels: int, max_dimension: int, skip_blank_pages: bool
) -> tuple[Image.Image, dict[str, Any]]:
    """Return an owned RGB image; preserve all pixels when correcting geometry."""
    image, detail = prepare_raster(original, max_pixels=max_pixels, max_dimension=max_dimension)
    operations = detail["operations"]
    try:
        if skip_blank_pages and is_blank(image):
            detail["status"] = "skipped"
            # No enhancement is needed for a page that will not be analyzed.
            detail["operations"] = []
            return image, detail
        gray = np.asarray(image.convert("L"))
        angle, confidence = deskew_angle(gray)
        if angle:
            radians = math.radians(abs(angle))
            check_size(
                math.ceil(image.width * math.cos(radians) + image.height * math.sin(radians)) + 2,
                math.ceil(image.height * math.cos(radians) + image.width * math.sin(radians)) + 2,
                max_pixels=max_pixels,
                max_dimension=max_dimension,
            )
            rotated = image.rotate(
                angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white"
            )
            image.close()
            image = rotated
            operations.append("deskew")
            detail.update(rotation_degrees=round(angle, 3), line_agreement=round(confidence, 3))
        # Preserve tones. Global percentiles cannot distinguish faint text from paper
        # and scan noise; stretching them clips letter edges and amplifies color noise.
        # Tonal changes need a validated quality check before they can be automatic.
        detail.update(
            width=image.width,
            height=image.height,
            status="adjusted" if operations else "unchanged",
        )
        return image, detail
    except Exception:  # noqa: BLE001 — release owned memory before the caller applies fallback
        image.close()
        raise
