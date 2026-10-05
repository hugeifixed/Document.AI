"""Synthetic safety/geometry tests; optional extra is not needed by ordinary CI."""

import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytest.importorskip("PIL")
pytest.importorskip("cv2")
pytest.importorskip("pypdfium2")

import numpy as np
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from docai import input_quality
from docai.exceptions import NormalizationFailed, NormalizationLimitExceeded, ValidationFailed
from docai.input_quality import native
from docai.input_quality.analysis import is_blank
from docai.input_quality.pdf import PDFIUM_LOCK, render_page, write_image_pdf
from docai.input_quality.pdf_inspection import page_detail
from docai.schemas.config import InputQualityConfig
from docai.synthetic.pdfwriter import write_pdf


@pytest.fixture(autouse=True)
def enable(settings):
    settings.DOCAI_IMAGE_NORMALIZATION_ENABLED = True


def _policy(**kwargs):
    return InputQualityConfig(mode="adaptive", **kwargs)


def _form(mode="RGB"):
    image = Image.new(mode, (800, 1000), 240 if mode == "L" else "white")
    draw = ImageDraw.Draw(image)
    draw.text((50, 30), "Account and tax statement", fill=0 if mode == "L" else "black")
    for y in range(120, 920, 80):
        draw.line((70, y, 720, y), fill=0 if mode == "L" else "black", width=2)
    return image


def test_clean_digital_pdf_bypasses_rendering_with_indirect_resources(tmp_path, monkeypatch):
    original = PdfReader(io.BytesIO(write_pdf([["Account 123", "Total 540"]])))
    writer = PdfWriter()
    page = writer.add_page(original.pages[0])
    page[NameObject("/Resources")] = writer._add_object(page["/Resources"])
    path = tmp_path / "digital.pdf"
    writer.write(path)

    def forbidden(*args, **kwargs):
        pytest.fail("Digital pages must retain their original PDF objects")

    monkeypatch.setattr(native, "render_page", forbidden)
    with input_quality.prepare_input(path, source_format="pdf", config=_policy()) as prepared:
        assert prepared.path == path
        assert prepared.summary["status"] == "bypassed"
        assert prepared.page_details[0]["has_text_layer"] is True
        assert prepared.page_details[0]["unit"] == "point"


def test_lossless_image_pdf_renders_real_pixels_and_cleans_native_handles(tmp_path):
    path = tmp_path / "scan.pdf"
    original = _form()
    write_image_pdf(original, path, dpi=300)
    rendered, dpi = render_page(path, 0, max_pixels=20_000_000, max_dimension=10_000)
    try:
        assert rendered.size == original.size
        assert 299 <= dpi <= 300
        assert np.asarray(rendered).min() < 10
        assert rendered.getpixel((400, 500)) == (255, 255, 255)
    finally:
        rendered.close()
        original.close()
    # File handles must be released before temporary-file removal, including on Windows.
    path.unlink()
    assert not PDFIUM_LOCK.locked()


def test_pdfium_rendering_is_serialized_and_images_survive_bitmap_close(tmp_path):
    path = tmp_path / "scan.pdf"
    write_image_pdf(_form(), path, dpi=300)

    def read(_):
        image, _dpi = render_page(path, 0, max_pixels=20_000_000, max_dimension=10_000)
        try:
            return image.size, int(np.asarray(image).min())
        finally:
            image.close()

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(read, range(6)))
    assert all(size == (800, 1000) and darkest < 10 for size, darkest in results)
    assert not PDFIUM_LOCK.locked()


def test_exif_orientation_is_applied_and_temporary_pdf_has_correct_geometry(tmp_path):
    path = tmp_path / "phone.jpg"
    image = _form()
    exif = image.getexif()
    exif[274] = 6
    image.save(path, exif=exif)
    original_bytes = path.read_bytes()
    with input_quality.prepare_input(path, source_format="jpeg", config=_policy()) as prepared:
        assert prepared.source_format == "pdf"
        assert prepared.summary["pages_adjusted"] == 1
        detail = prepared.page_details[0]
        assert "exif_orientation" in detail["operations"]
        assert detail["width"] > detail["height"]
        temporary_path = prepared.path
        assert temporary_path.exists()
        assert float(PdfReader(temporary_path).pages[0].mediabox.width) == pytest.approx(
            detail["width"]
        )
    assert not temporary_path.exists()
    assert path.read_bytes() == original_bytes


def test_skew_is_corrected_without_cropping(tmp_path):
    image = _form().rotate(-4, expand=True, fillcolor="white")
    path = tmp_path / "skew.png"
    image.save(path)
    with input_quality.prepare_input(path, source_format="png", config=_policy()) as prepared:
        detail = prepared.page_details[0]
        assert "deskew" in detail["operations"]
        assert detail["rotation_degrees"] == pytest.approx(4, abs=0.3)
        assert detail["line_agreement"] >= 0.9
        assert detail["width"] * 300 / 72 > image.width
        assert detail["height"] * 300 / 72 > image.height


@pytest.mark.parametrize("source_format", ["png", "pdf"])
@pytest.mark.parametrize("noisy", [False, True])
def test_low_contrast_and_noisy_scans_keep_original_tones(tmp_path, source_format, noisy):
    image = Image.new("RGB", (500, 600), (210, 210, 210))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 280, 550), fill=(180, 180, 180))
    draw.text((60, 70), "Wages 1200.00   Tax 100.00", fill=(70, 70, 70))
    if noisy:
        # Colored scan noise must not be stretched into saturated fringes around letters.
        noise = np.random.default_rng(42).integers(-8, 9, (*image.size[::-1], 3))
        pixels = np.clip(np.asarray(image).astype(np.int16) + noise, 0, 255).astype(np.uint8)
        image.close()
        image = Image.fromarray(pixels)
    path = tmp_path / f"scan.{source_format}"
    if source_format == "pdf":
        write_image_pdf(image, path, dpi=300)
    else:
        image.save(path)
    image.close()
    original_bytes = path.read_bytes()
    with input_quality.prepare_input(
        path, source_format=source_format, config=_policy()
    ) as prepared:
        assert prepared.path == path
        assert prepared.summary["status"] == "bypassed"
        assert prepared.page_details[0]["operations"] == []
        assert prepared.path.read_bytes() == original_bytes


@pytest.mark.parametrize("fill", [(251, 251, 251), (200, 200, 200), (255, 251, 210)])
def test_sparse_faint_marks_are_never_treated_as_blank(fill):
    image = Image.new("RGB", (1000, 1500), "white")
    ImageDraw.Draw(image).line((500, 700, 502, 702), fill=fill, width=2)
    assert not is_blank(image)
    assert is_blank(Image.new("RGB", (1000, 1500), "white"))


def test_multipage_tiff_preserves_all_frames_and_selects_original_page_numbers(tmp_path):
    path = tmp_path / "batch.tiff"
    first, blank, last = _form(), Image.new("RGB", (800, 1000), "white"), _form()
    first.save(path, save_all=True, append_images=[blank, last], compression="tiff_deflate")
    with input_quality.prepare_input(
        path, source_format="tiff", config=_policy(skip_blank_pages=True)
    ) as prepared:
        assert prepared.source_format == "pdf"
        assert len(PdfReader(prepared.path).pages) == 3
        assert prepared.selected_pages == "1,3"
        assert prepared.summary["pages_skipped"] == 1
        assert [page["page"] for page in prepared.page_details] == [1, 2, 3]
        assert prepared.page_details[1]["status"] == "skipped"
    with input_quality.prepare_input(path, source_format="tiff", config=_policy()) as prepared:
        assert prepared.selected_pages is None
        assert prepared.summary["pages_skipped"] == 0
        assert prepared.source_format == "pdf"


def test_all_blank_input_fails_before_di(tmp_path):
    path = tmp_path / "blank.png"
    Image.new("RGB", (100, 200), "white").save(path)
    with (
        pytest.raises(ValidationFailed) as error,
        input_quality.prepare_input(
            path, source_format="png", config=_policy(skip_blank_pages=True)
        ),
    ):
        pytest.fail("No selected pages must never silently mean analyze all pages")
    assert error.value.error_code == "EMPTY_LAYOUT"


def test_mixed_pdf_preserves_native_text_while_adjusting_scanned_page(tmp_path):
    scan_path = tmp_path / "scan.pdf"
    write_image_pdf(_form().rotate(-3, expand=True, fillcolor="white"), scan_path, dpi=300)
    digital = PdfReader(io.BytesIO(write_pdf([["Account 123 Total 540"]])))
    writer = PdfWriter()
    writer.add_page(digital.pages[0])
    writer.add_page(PdfReader(scan_path).pages[0])
    path = tmp_path / "mixed.pdf"
    writer.write(path)
    with input_quality.prepare_input(path, source_format="pdf", config=_policy()) as prepared:
        assert prepared.summary["pages_adjusted"] == 1
        assert [page["has_text_layer"] for page in prepared.page_details] == [True, False]
        reader = PdfReader(prepared.path)
        assert len(reader.pages) == 2
        assert reader.pages[0].extract_text() == digital.pages[0].extract_text()
        assert prepared.page_details[0]["status"] == "bypassed"
        assert prepared.page_details[1]["status"] == "adjusted"


def test_hidden_ocr_text_is_not_native_text_and_does_not_allow_blank_skipping(tmp_path):
    writer = PdfWriter()
    digital = PdfReader(io.BytesIO(write_pdf([["Retained OCR content"]])))
    page = writer.add_page(digital.pages[0])
    content = DecodedStreamObject()
    original_content = page.get_contents()
    assert original_content is not None
    content.set_data(b"3 Tr\n" + original_content.get_data())
    page[NameObject("/Contents")] = writer._add_object(content)
    path = tmp_path / "hidden.pdf"
    writer.write(path)
    detail = page_detail(PdfReader(path).pages[0], 1)
    assert detail["has_text_layer"] is False
    assert detail["has_existing_text"] is True
    with input_quality.prepare_input(
        path, source_format="pdf", config=_policy(skip_blank_pages=True)
    ) as prepared:
        assert prepared.summary["pages_skipped"] == 0


def test_page_failure_keeps_other_adjustments_and_original_failed_page(tmp_path, monkeypatch):
    scan_path = tmp_path / "scan.pdf"
    write_image_pdf(_form().rotate(-3, expand=True, fillcolor="white"), scan_path, dpi=300)
    writer = PdfWriter()
    writer.append(PdfReader(scan_path))
    writer.append(PdfReader(scan_path))
    path = tmp_path / "batch.pdf"
    writer.write(path)
    real_render = native.render_page

    def render(source, index, **kwargs):
        if index == 1:
            raise RuntimeError("Simulated native renderer failure")
        return real_render(source, index, **kwargs)

    monkeypatch.setattr(native, "render_page", render)
    with input_quality.prepare_input(path, source_format="pdf", config=_policy()) as prepared:
        assert prepared.summary["status"] == "fallback"
        assert prepared.summary["pages_adjusted"] == 1
        assert prepared.summary["warnings"][0]["pages"] == [2]
        assert prepared.summary["warnings"][0]["code"] == "NORMALIZATION_FALLBACK"
        assert prepared.page_details[1]["status"] == "fallback"
        assert prepared.page_details[1]["unit"] == "point"
        assert len(PdfReader(prepared.path).pages) == 2


@pytest.mark.parametrize(
    "limit", ["DOCAI_IMAGE_NORMALIZATION_MAX_PIXELS", "DOCAI_IMAGE_NORMALIZATION_MAX_OUTPUT_MB"]
)
def test_enhancement_limit_fallback_requires_safe_metadata_preparation(tmp_path, settings, limit):
    path = tmp_path / "large.png"
    _form("L").save(path)
    setattr(settings, limit, 1 if limit.endswith("PIXELS") else 0)
    if limit.endswith("PIXELS"):
        # Raster metadata can itself trigger decoding. No original may bypass
        # that mandatory preparation bound after enhancement fails.
        with (
            pytest.raises(NormalizationLimitExceeded),
            input_quality.prepare_input(path, source_format="png", config=_policy()),
        ):
            pytest.fail("Oversized metadata preparation must not fall back to original input")
        return
    with input_quality.prepare_input(path, source_format="png", config=_policy()) as prepared:
        assert prepared.path == path
        assert prepared.summary["status"] == "fallback"
        assert prepared.summary["warnings"][0]["code"] == "NORMALIZATION_LIMIT_EXCEEDED"
        assert prepared.page_details == []


def test_unreadable_original_cannot_be_a_successful_fallback(tmp_path):
    with (
        pytest.raises(NormalizationFailed),
        input_quality.prepare_input(
            tmp_path / "missing.png", source_format="png", config=_policy()
        ),
    ):
        pytest.fail("Missing original must fail")


@pytest.mark.parametrize("callback", ["check_cancelled", "progress"])
def test_caller_cancellation_propagates_and_cleans_temporary_files(tmp_path, monkeypatch, callback):
    path = tmp_path / "scan.png"
    _form("L").save(path)
    directories = []
    original_temp = input_quality.TemporaryDirectory

    def temporary(**kwargs):
        directory = original_temp(dir=tmp_path, **kwargs)
        directories.append(Path(directory.name))
        return directory

    class Cancelled(Exception):
        pass

    def cancel(*args):
        raise Cancelled("Run cancelled")

    monkeypatch.setattr(input_quality, "TemporaryDirectory", temporary)
    with (
        pytest.raises(Cancelled),
        input_quality.prepare_input(
            path, source_format="png", config=_policy(), **{callback: cancel}
        ),
    ):
        pytest.fail("Cancellation must never be converted to fallback")
    assert directories and not any(directory.exists() for directory in directories)


def test_di_errors_are_not_caught_by_normalization(tmp_path):
    path = tmp_path / "scan.png"
    _form("L").save(path)
    with (
        pytest.raises(RuntimeError, match="DI timed out"),
        input_quality.prepare_input(path, source_format="png", config=_policy()) as prepared,
    ):
        temporary = prepared.path
        raise RuntimeError("DI timed out")
    assert not temporary.exists()


def test_page_range_compression():
    assert native.selected_page_ranges([1, 2, 3, 5, 7, 8]) == "1-3,5,7-8"


def test_output_byte_limit_discards_lossless_raster_copy(tmp_path, settings):
    settings.DOCAI_IMAGE_NORMALIZATION_MAX_OUTPUT_MB = 1
    rng = np.random.default_rng(12)
    path = tmp_path / "noisy.png"
    Image.fromarray(rng.integers(0, 256, (1200, 1200), dtype=np.uint8)).save(path)
    with input_quality.prepare_input(path, source_format="png", config=_policy()) as prepared:
        assert prepared.path == path
        assert prepared.summary["status"] == "fallback"
        assert prepared.summary["warnings"][0]["code"] == "NORMALIZATION_LIMIT_EXCEEDED"


def test_vector_only_pages_are_preserved_and_blank_pdf_pages_can_be_skipped(tmp_path):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    content = DecodedStreamObject()
    content.set_data(b"0 0 0 RG 50 50 m 400 200 l S")
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.add_blank_page(width=600, height=800)
    path = tmp_path / "vector.pdf"
    writer.write(path)
    with input_quality.prepare_input(
        path, source_format="pdf", config=_policy(skip_blank_pages=True)
    ) as prepared:
        assert prepared.path == path
        assert prepared.selected_pages == "1"
        assert prepared.page_details[0]["status"] == "bypassed"
        assert prepared.page_details[1]["status"] == "skipped"


def test_alpha_is_composited_on_white_without_losing_visible_content(tmp_path):
    path = tmp_path / "transparent.png"
    image = Image.new("RGBA", (100, 200), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((25, 40, 75, 80), fill=(30, 30, 30, 255))
    image.save(path)
    with input_quality.prepare_input(path, source_format="png", config=_policy()) as prepared:
        assert prepared.summary["pages_adjusted"] == 1
        rendered, _dpi = render_page(prepared.path, 0, max_pixels=1_000_000, max_dimension=1000)
        try:
            assert rendered.getpixel((5, 5)) == (255, 255, 255)
            assert rendered.getpixel((50, 60)) == (30, 30, 30)
        finally:
            rendered.close()
