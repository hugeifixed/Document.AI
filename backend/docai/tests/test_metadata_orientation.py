"""Independent pixel landmarks verify metadata preparation, source reuse and isolation."""

from __future__ import annotations

import builtins
import io
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, TiffImagePlugin
from pypdf import PageObject, PdfReader, PdfWriter

from docai import input_quality
from docai.exceptions import NormalizationFailed, NormalizationLimitExceeded
from docai.schemas.config import InputQualityConfig
from docai.schemas.layout import LayoutDocument, LayoutPage, Span, Word
from docai.services import layouts
from docai.synthetic.pdfwriter import write_pdf


def marked_image():
    image = Image.new("RGB", (300, 200), "white")
    ImageDraw.Draw(image).rectangle((45, 45, 75, 75), fill="red")
    return image


def save_oriented(path, format_name, orientation):
    with marked_image() as image:
        exif = Image.Exif()
        exif[274] = orientation
        image.save(path, format_name, exif=exif)


def embedded_image(page: PageObject) -> Image.Image:
    image = page.images[0].image
    assert image is not None
    return image


def assert_marker(image, x, y):
    pixel = image.convert("RGB").getpixel((round(x * image.width), round(y * image.height)))
    assert isinstance(pixel, tuple)
    assert pixel[0] > 240 and max(pixel[1:]) < 15


@pytest.mark.parametrize("format_name", ["JPEG", "PNG", "TIFF"])
@pytest.mark.parametrize(
    "orientation,size,landmark",
    [
        (1, (300, 200), (0.2, 0.3)),
        (2, (300, 200), (0.8, 0.3)),
        (3, (300, 200), (0.8, 0.7)),
        (4, (300, 200), (0.2, 0.7)),
        (5, (200, 300), (0.3, 0.2)),
        (6, (200, 300), (0.7, 0.2)),
        (7, (200, 300), (0.7, 0.8)),
        (8, (200, 300), (0.3, 0.8)),
    ],
)
def test_metadata_preparation_matches_independent_landmarks_with_enhancement_off(
    tmp_path, settings, monkeypatch, format_name, orientation, size, landmark
):
    settings.DOCAI_IMAGE_NORMALIZATION_ENABLED = False
    source = tmp_path / f"form.{format_name.lower()}"
    save_oriented(source, format_name, orientation)
    original_bytes = source.read_bytes()
    original_import = builtins.__import__

    def without_enhancement(name, *args, **kwargs):
        if name.split(".")[0] in {"cv2", "numpy", "pypdfium2"} or name.endswith("analysis"):
            raise ImportError("Enhancement is unavailable in this base install")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_enhancement)
    with input_quality.prepare_input(
        source, source_format=format_name.lower(), config=InputQualityConfig()
    ) as prepared:
        if orientation == 1 and format_name != "TIFF":
            assert prepared.path == source and prepared.path.read_bytes() == original_bytes
            return
        assert prepared.source_format == "pdf"
        reader = PdfReader(prepared.path)
        assert len(reader.pages) == 1
        image = embedded_image(reader.pages[0])
        assert image.size == size
        assert_marker(image, *landmark)
        detail = prepared.page_details[0]
        assert detail["original_width"] == 300 and detail["original_height"] == 200
        assert detail["exif_orientation"] == orientation
        assert detail["operations"].count("exif_orientation") == (orientation != 1)
        assert prepared.selected_pages is None
        path = prepared.path
        prepared_bytes = path.read_bytes()
        # Re-entering the shared boundary cannot apply the original metadata again.
        with input_quality.prepare_input(
            path, source_format="pdf", config=InputQualityConfig()
        ) as second:
            assert second.path == path and second.path.read_bytes() == prepared_bytes
    assert not path.exists()
    assert source.read_bytes() == original_bytes


def test_mixed_tiff_frame_rotations_preserve_page_order_and_raw_metadata(tmp_path):
    source = tmp_path / "bundle.tiff"
    with TiffImagePlugin.AppendingTiffWriter(source, new=True) as writer:
        for orientation in (1, 6, 3, 8):
            with marked_image() as image:
                image.save(writer, "TIFF", tiffinfo={274: orientation})
                writer.newFrame()
    with input_quality.prepare_input(
        source, source_format="tiff", config=InputQualityConfig()
    ) as prepared:
        reader = PdfReader(prepared.path)
        assert len(reader.pages) == 4
        for page, size, landmark in zip(
            reader.pages,
            [(300, 200), (200, 300), (300, 200), (200, 300)],
            [(0.2, 0.3), (0.7, 0.2), (0.8, 0.7), (0.3, 0.8)],
            strict=True,
        ):
            image = embedded_image(page)
            assert image.size == size
            assert_marker(image, *landmark)
        assert [p["page"] for p in prepared.page_details] == [1, 2, 3, 4]
        assert [p["exif_orientation"] for p in prepared.page_details] == [1, 6, 3, 8]
        assert prepared.summary["pages_adjusted"] == 3
        assert prepared.selected_pages is None


def test_mixed_pdf_rotation_metadata_preserves_native_pages_and_original_bytes(tmp_path):
    source = tmp_path / "bundle.pdf"
    writer = PdfWriter()
    original = PdfReader(io.BytesIO(write_pdf([["First"], ["Second"], ["Third"]])))
    for page, rotation in zip(original.pages, (0, 90, 180), strict=True):
        writer.add_page(page).rotate(rotation)
    writer.write(source)
    original_bytes = source.read_bytes()
    with input_quality.prepare_input(
        source, source_format="pdf", config=InputQualityConfig()
    ) as prepared:
        assert prepared.path == source and prepared.path.read_bytes() == original_bytes
        pages = PdfReader(prepared.path).pages
        assert [page.rotation for page in pages] == [0, 90, 180]
        assert [page.extract_text().strip() for page in pages] == ["First", "Second", "Third"]


def test_square_image_metadata_cannot_be_inferred_from_dimensions(tmp_path):
    source = tmp_path / "square.png"
    with Image.new("RGB", (300, 300), "white") as image:
        ImageDraw.Draw(image).rectangle((45, 75, 75, 105), fill="red")
        exif = Image.Exif()
        exif[274] = 3
        image.save(source, exif=exif)
    with input_quality.prepare_input(
        source, source_format="png", config=InputQualityConfig()
    ) as prepared:
        prepared_image = embedded_image(PdfReader(prepared.path).pages[0])
        assert prepared_image.size == (300, 300)
        assert_marker(prepared_image, 0.8, 0.7)


@pytest.mark.parametrize("mode", ["off", "adaptive"])
def test_required_metadata_failure_never_publishes_original_or_partial_pixels(
    tmp_path, settings, monkeypatch, mode
):
    from docai.input_quality import native

    settings.DOCAI_IMAGE_NORMALIZATION_ENABLED = True
    monkeypatch.setattr(input_quality, "_availability", lambda: (True, "available"))
    source = tmp_path / "oriented.png"
    save_oriented(source, "PNG", 6)
    temporary = []
    original_temp = input_quality.TemporaryDirectory

    def temporary_directory(**kwargs):
        directory = original_temp(**kwargs)
        temporary.append(directory.name)
        return directory

    def broken_save(*args, **kwargs):
        raise OSError("simulated encoder failure")

    monkeypatch.setattr(input_quality, "TemporaryDirectory", temporary_directory)
    monkeypatch.setattr(native, "write_image_pdf", broken_save)
    with (
        pytest.raises(NormalizationFailed),
        input_quality.prepare_input(
            source, source_format="png", config=InputQualityConfig(mode=mode)
        ),
    ):
        pytest.fail("An unnormalized original must not reach DI")
    from pathlib import Path

    assert temporary and all(not Path(path).exists() for path in temporary)


def test_optional_enhancement_failure_still_prepares_metadata(tmp_path, settings, monkeypatch):
    pytest.importorskip("cv2")
    pytest.importorskip("pypdfium2")
    from docai.input_quality import analysis

    settings.DOCAI_IMAGE_NORMALIZATION_ENABLED = True
    source = tmp_path / "oriented.png"
    save_oriented(source, "PNG", 6)

    def broken_enhancement(*args, **kwargs):
        raise RuntimeError("simulated enhancement failure")

    monkeypatch.setattr(analysis, "deskew_angle", broken_enhancement)
    with input_quality.prepare_input(
        source, source_format="png", config=InputQualityConfig(mode="adaptive")
    ) as prepared:
        assert prepared.source_format == "pdf" and prepared.path != source
        assert prepared.summary["status"] == "fallback"
        assert prepared.summary["warnings"][0]["code"] == "NORMALIZATION_FALLBACK"
        prepared_image = embedded_image(PdfReader(prepared.path).pages[0])
        assert prepared_image.size == (200, 300)
        assert_marker(prepared_image, 0.7, 0.2)


@pytest.mark.parametrize("orientation", [None, 6])
def test_metadata_limits_fail_before_decode_or_di(tmp_path, settings, monkeypatch, orientation):
    from PIL import PngImagePlugin

    source = tmp_path / "oriented.png"
    if orientation is None:
        with marked_image() as image:
            image.save(source, "PNG")
    else:
        save_oriented(source, "PNG", orientation)
    settings.DOCAI_IMAGE_NORMALIZATION_MAX_PIXELS = 1

    def forbidden_decode(*args, **kwargs):
        pytest.fail("Pixels were decoded before the preparation size bound")

    monkeypatch.setattr(PngImagePlugin.PngImageFile, "load", forbidden_decode)
    with (
        pytest.raises(NormalizationLimitExceeded),
        input_quality.prepare_input(source, source_format="png", config=InputQualityConfig()),
    ):
        pytest.fail("Oversized metadata preparation must stop before provider calls")


@pytest.mark.django_db
def test_playground_upload_uses_the_same_metadata_preparation_boundary(
    project, admin, tmp_path, monkeypatch
):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from docai.services import playground

    source = tmp_path / "phone.png"
    save_oriented(source, "PNG", 6)
    session = playground.create_session(project.pk, admin)
    sample = playground.attach_upload(session, SimpleUploadedFile("phone.png", source.read_bytes()))
    calls = []

    def analyze(path, *, document_id, source_format, **options):
        assert source_format == "pdf"
        image = embedded_image(PdfReader(path).pages[0])
        assert image.size == (200, 300)
        assert_marker(image, 0.7, 0.2)
        calls.append(path)
        return LayoutDocument(
            document_id=document_id,
            source_format="pdf",
            service="fixture",
            units=[LayoutPage(index=0, number=1, content="Account form")],
        )

    monkeypatch.setattr(
        playground,
        "get_layout_provider_for_format",
        lambda *_, **kwargs: SimpleNamespace(key="fixture", supports_ocr=True, analyze=analyze),
    )
    result = playground._sample_layout(sample)
    assert result.pages[0].content == "Account form"
    assert len(calls) == 1 and not calls[0].exists()


@pytest.mark.django_db
def test_off_mode_ocr_and_review_share_exact_prepared_source_and_versioned_cache(
    dataset, api, settings, tmp_path, monkeypatch
):
    from docai.adapters.storage import read_bytes, save_bytes
    from docai.models import Document

    settings.MEDIA_ROOT = tmp_path / "media"
    settings.DOCAI_IMAGE_NORMALIZATION_ENABLED = False
    source = tmp_path / "phone.png"
    save_oriented(source, "PNG", 6)
    original_bytes = source.read_bytes()
    storage_path, digest = save_bytes("tests/phone.png", original_bytes)
    document = Document.objects.create(
        dataset=dataset,
        original_filename="phone.png",
        file_format="png",
        mime_type="image/png",
        sha256=digest,
        size_bytes=len(original_bytes),
        storage_path=storage_path,
        page_count=1,
        status="validated",
    )
    calls = []

    def analyze(path, *, document_id, source_format, **options):
        assert source_format == "pdf"
        calls.append(path.read_bytes())
        page = PdfReader(path).pages[0]
        assert_marker(embedded_image(page), 0.7, 0.2)
        return LayoutDocument(
            document_id=document_id,
            source_format="pdf",
            service="fixture",
            units=[
                LayoutPage(
                    index=0,
                    number=1,
                    width=float(page.mediabox.width),
                    height=float(page.mediabox.height),
                    unit="point",
                    content="100",
                    words=[
                        Word(
                            id="p1:w0",
                            text="100",
                            span=Span(offset=0, length=3),
                            polygon=[0.6, 0.1, 0.8, 0.1, 0.8, 0.3, 0.6, 0.3],
                        )
                    ],
                )
            ],
        )

    monkeypatch.setattr(
        layouts,
        "get_layout_provider_for_format",
        lambda *_, **kwargs: SimpleNamespace(key="fixture", supports_ocr=True, analyze=analyze),
    )
    layouts.get_or_build_layout(document)
    old_artifact = layouts.artifact_for_document(document)
    assert old_artifact is not None and old_artifact.source_artifact is not None
    assert read_bytes(old_artifact.source_artifact.storage_path) == calls[0]
    detail = api.get(f"/api/v1/documents/{document.pk}/").json()["data"]
    assert detail["processing_source"]["file_format"] == "pdf"
    assert detail["processing_source"]["is_original"] is False
    response = api.get(detail["processing_source"]["url"])
    assert b"".join(response.streaming_content) == calls[0]
    layouts.get_or_build_layout(document)
    assert len(calls) == 1
    monkeypatch.setattr(input_quality, "METADATA_REVISION", input_quality.METADATA_REVISION + 1)
    layouts.get_or_build_layout(document)
    assert len(calls) == 2
    new_artifact = layouts.artifact_for_document(document)
    assert new_artifact is not None and new_artifact.pk != old_artifact.pk
    historical = api.get(
        f"/api/v1/documents/{document.pk}/processing-source/?layout={old_artifact.pk}"
    )
    assert b"".join(historical.streaming_content) == calls[0]
    assert read_bytes(document.storage_path) == original_bytes
