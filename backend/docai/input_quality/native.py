"""Page-at-a-time native processor, loaded only for explicitly enabled adaptive input."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from django.conf import settings
from PIL import Image
from pypdf import PdfReader, PdfWriter

from docai.exceptions import NormalizationLimitExceeded, ValidationFailed
from docai.schemas.config import InputQualityConfig

from . import PreparedInput
from .analysis import check_size, improve_image, is_blank
from .pdf import page_detail, render_page, write_image_pdf


def selected_page_ranges(pages: list[int]) -> str:
    groups: list[str] = []
    start = end = pages[0]
    for page in pages[1:]:
        if page == end + 1:
            end = page
        else:
            groups.append(str(start) if start == end else f"{start}-{end}")
            start = end = page
    groups.append(str(start) if start == end else f"{start}-{end}")
    return ",".join(groups)


class _Preparation:
    def __init__(self, result: PreparedInput, directory: Path, config: InputQualityConfig):
        self.result = result
        self.directory = directory
        self.config = config
        self.max_pixels = settings.DOCAI_IMAGE_NORMALIZATION_MAX_PIXELS
        self.max_dimension = settings.DOCAI_IMAGE_NORMALIZATION_MAX_DIMENSION
        self.max_bytes = settings.DOCAI_IMAGE_NORMALIZATION_MAX_OUTPUT_MB * 1024 * 1024
        self.bytes_written = 0
        self.replacements: dict[int, Path] = {}
        if min(self.max_pixels, self.max_dimension, self.max_bytes) <= 0:
            raise NormalizationLimitExceeded()

    def save(self, image: Image.Image, detail: dict[str, Any], dpi: float) -> None:
        path = self.directory / f"p{detail['page']}.pdf"
        write_image_pdf(image, path, dpi=dpi)
        size = path.stat().st_size
        if self.bytes_written + size > self.max_bytes:
            path.unlink()
            raise NormalizationLimitExceeded()
        self.bytes_written += size
        self.replacements[detail["page"]] = path
        detail.update(
            width=image.width * 72 / dpi,
            height=image.height * 72 / dpi,
            unit="point",
            render_dpi=round(dpi, 2),
        )

    def improve(self, image: Image.Image, *, skip: bool) -> tuple[Image.Image, dict[str, Any]]:
        return improve_image(
            image,
            max_pixels=self.max_pixels,
            max_dimension=self.max_dimension,
            skip_blank_pages=skip,
        )

    def pdf_page(self, reader: PdfReader, index: int) -> None:
        page = reader.pages[index]
        detail = {
            "page": index + 1,
            "status": "unchanged",
            "operations": [],
            "width": float(page.mediabox.width),
            "height": float(page.mediabox.height),
            "unit": "point",
            "has_text_layer": False,
        }
        original_detail = detail.copy()
        try:
            detail = page_detail(page, index + 1)
            original_detail = detail.copy()
            self.improve_pdf_page(detail, index)
        except Exception as exc:  # noqa: BLE001 — retain the original PDF page on native failure
            # Keep source dimensions; no partially transformed frame is published.
            detail = original_detail
            detail.update(status="fallback", operations=[])
            limited = isinstance(exc, (NormalizationLimitExceeded, MemoryError, OverflowError))
            self.result.summary["warnings"].append(
                {
                    "code": "NORMALIZATION_LIMIT_EXCEEDED" if limited else "NORMALIZATION_FALLBACK",
                    "message": f"Scan enhancement {'exceeded processing limits' if limited else 'could not be completed'} for page {index + 1}. Processing continued with the original page.",
                    "pages": [index + 1],
                    "retryable": False,
                }
            )
        self.result.page_details.append(detail)

    def improve_pdf_page(self, detail: dict[str, Any], index: int) -> None:
        if not detail["has_text_layer"]:
            if not detail["has_raster_content"] and not self.config.skip_blank_pages:
                return
            original, dpi = render_page(
                self.result.path,
                index,
                max_pixels=self.max_pixels,
                max_dimension=self.max_dimension,
            )
            try:
                # Vector-only content is never rasterized for enhancement. Blank
                # detection may still inspect it, retaining any uncertain markings.
                if not detail["has_raster_content"]:
                    if not detail["has_existing_text"] and is_blank(original):
                        detail["status"] = "skipped"
                    return
                enhanced, facts = self.improve(
                    original,
                    skip=self.config.skip_blank_pages and not detail["has_existing_text"],
                )
                try:
                    # Unchanged/skipped PDF pages retain their exact original page objects.
                    detail.update(status=facts["status"], operations=facts["operations"])
                    if facts["status"] == "adjusted":
                        detail.update(facts)
                        self.save(enhanced, detail, dpi)
                finally:
                    enhanced.close()
            finally:
                original.close()

    def image_page(self, source: Image.Image, index: int) -> None:
        source.seek(index)
        check_size(*source.size, max_pixels=self.max_pixels, max_dimension=self.max_dimension)
        # Decode only this frame. Do not collect TIFF frames or decoded pages in a list.
        original = source.copy()
        try:
            enhanced, detail = self.improve(original, skip=self.config.skip_blank_pages)
            detail["page"] = index + 1
            try:
                self.save(enhanced, detail, 300)
            finally:
                enhanced.close()
        finally:
            original.close()
        self.result.page_details.append(detail)

    def publish(self, original: PdfReader | None, check_cancelled: Callable[[], None]) -> None:
        selected = [
            page["page"] for page in self.result.page_details if page["status"] != "skipped"
        ]
        if not selected:
            raise ValidationFailed(
                "Every page was identified as blank. Use original input to analyze all pages.",
                error_code="EMPTY_LAYOUT",
            )
        summary = self.result.summary
        summary["pages_skipped"] = len(self.result.page_details) - len(selected)
        summary["pages_adjusted"] = sum(
            page["status"] == "adjusted" for page in self.result.page_details
        )
        if summary["pages_skipped"]:
            self.result.selected_pages = selected_page_ranges(selected)
        # TIFF has no dependable browser preview. A lossless PDF makes every frame
        # reviewable, even when no scan correction was indicated by the heuristics.
        convert_tiff = self.result.source_format in {"tif", "tiff"}
        if not summary["pages_adjusted"] and not convert_tiff:
            # No derived input is necessary. Image provenance must describe original pixels.
            if original is None:
                for page in self.result.page_details:
                    page.update(
                        width=page["original_width"], height=page["original_height"], unit="pixel"
                    )
            summary["status"] = (
                "fallback"
                if summary["warnings"]
                else "applied"
                if summary["pages_skipped"]
                else "bypassed"
            )
            return
        output = self.directory / "prepared.pdf"
        writer = PdfWriter()
        try:
            for page in self.result.page_details:
                check_cancelled()
                replacement = self.replacements.get(page["page"])
                if replacement is not None:
                    reader = PdfReader(str(replacement))
                    try:
                        writer.add_page(reader.pages[0])
                    finally:
                        reader.close()
                elif original is not None:
                    writer.add_page(original.pages[page["page"] - 1])
            writer.write(str(output))
        finally:
            writer.close()
        if output.stat().st_size > self.max_bytes:
            raise NormalizationLimitExceeded()
        self.result.path = output
        self.result.source_format = "pdf"
        summary.update(
            status="fallback" if summary["warnings"] else "applied",
            output_bytes=output.stat().st_size,
        )


def prepare_document(
    result: PreparedInput,
    *,
    directory: Path,
    config: InputQualityConfig,
    check_cancelled: Callable[[], None],
    progress: Callable[[int, int], None],
) -> None:
    preparation = _Preparation(result, directory, config)
    original: PdfReader | None = None
    image: Image.Image | None = None
    try:
        if result.source_format == "pdf":
            original = PdfReader(str(result.path))
            total = len(original.pages)
        else:
            image = Image.open(result.path)
            total = getattr(image, "n_frames", 1)
        if not 0 < total <= settings.DOCAI["MAX_PAGES"]:
            raise NormalizationLimitExceeded()
        progress(0, total)
        for index in range(total):
            check_cancelled()
            if original is not None:
                preparation.pdf_page(original, index)
            elif image is not None:
                preparation.image_page(image, index)
            result.summary["pages_examined"] = index + 1
            progress(index + 1, total)
        check_cancelled()
        preparation.publish(original, check_cancelled)
    finally:
        if original is not None:
            original.close()
        if image is not None:
            image.close()
