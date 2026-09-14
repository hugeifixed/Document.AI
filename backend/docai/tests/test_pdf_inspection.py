"""Real PDF content inspection and off-mode Azure capture need no native packages."""

import builtins
import io
from types import SimpleNamespace

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from docai.adapters.layout import azure_di
from docai.exceptions import SpanMappingFailed
from docai.input_quality.pdf_inspection import page_detail, text_layers
from docai.services import ingestion, labeling, layouts, runs
from docai.synthetic.pdfwriter import write_pdf


def pdf_bytes(kinds):
    writer = PdfWriter()
    digital = PdfReader(io.BytesIO(write_pdf([["100.00"]])))
    for kind in kinds:
        page = writer.add_page(digital.pages[0])
        content = DecodedStreamObject()
        contents = page.get_contents()
        assert contents is not None
        original = contents.get_data()
        if kind == "scan":
            # An actual page-sized image XObject; no image decoding library needed.
            pixels = DecodedStreamObject()
            pixels.set_data(b"\x00")
            pixels.update(
                {
                    NameObject("/Type"): NameObject("/XObject"),
                    NameObject("/Subtype"): NameObject("/Image"),
                    NameObject("/Width"): NumberObject(1),
                    NameObject("/Height"): NumberObject(1),
                    NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                    NameObject("/BitsPerComponent"): NumberObject(8),
                }
            )
            source_resources = page["/Resources"]
            assert isinstance(source_resources, DictionaryObject)
            resources = DictionaryObject(source_resources)
            resources[NameObject("/XObject")] = DictionaryObject(
                {NameObject("/Scan"): writer._add_object(pixels)}
            )
            page[NameObject("/Resources")] = writer._add_object(resources)
            content.set_data(
                f"q {page.mediabox.width} 0 0 {page.mediabox.height} 0 0 cm /Scan Do Q\n".encode()
                + b"3 Tr\n"
                + original
            )
        elif kind == "hidden":
            content.set_data(b"q 3 Tr\n" + original + b"\nQ")
        else:
            content.set_data(original)
        page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    writer.close()
    return output.getvalue()


def block_native_imports(monkeypatch):
    original_import = builtins.__import__

    def without_native(name, *args, **kwargs):
        if name.split(".")[0] in {"PIL", "cv2", "pypdfium2", "numpy"} or name.endswith("native"):
            raise AssertionError("Off-mode PDF inspection imported an optional native library")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_native)


@pytest.mark.parametrize("kinds", [["digital"], ["scan"], ["digital", "scan", "hidden"]])
def test_pdf_inspection_proves_text_per_page_without_native_dependencies(
    tmp_path, monkeypatch, kinds
):
    path = tmp_path / "mixed.pdf"
    path.write_bytes(pdf_bytes(kinds))
    block_native_imports(monkeypatch)
    assert text_layers(path) == {index: kind == "digital" for index, kind in enumerate(kinds)}
    with path.open("rb") as stream:
        reader = PdfReader(stream)
        for index, page in enumerate(reader.pages):
            detail = page_detail(page, index + 1)
            assert detail["has_text_layer"] == (kinds[index] == "digital")
            assert detail["has_existing_text"]
            assert detail["has_raster_content"] == (kinds[index] == "scan")


def test_unknown_or_damaged_pdf_never_claims_native_text(tmp_path, monkeypatch):
    from docai.input_quality import pdf_inspection

    missing = tmp_path / "missing.pdf"
    assert text_layers(missing) == {}
    missing.write_bytes(b"%PDF unreadable")
    assert text_layers(missing) == {}
    missing.write_bytes(pdf_bytes(["digital", "digital"]))
    original = pdf_inspection.native_text
    attempts = 0

    def inspect(page):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("Unsupported content on this page")
        return original(page)

    monkeypatch.setattr(pdf_inspection, "native_text", inspect)
    assert text_layers(missing) == {0: False, 1: True}


@pytest.mark.django_db
@pytest.mark.parametrize("kinds", [["digital"], ["scan"], ["digital", "scan", "hidden"]])
def test_off_azure_layout_keeps_native_selection_and_pdfjs_capture_only_for_digital_pages(
    dataset, admin, sample_workflow, monkeypatch, kinds
):
    data = pdf_bytes(kinds)
    document = ingestion.ingest_upload(dataset, "mixed.pdf", data, user=admin)
    adapter = object.__new__(azure_di.AzureDocumentIntelligenceLayout)
    adapter.timeout, adapter.api_version = 1, "2024-11-30"
    result = SimpleNamespace(
        content="100.00" * len(kinds),
        paragraphs=[],
        tables=[],
        sections=[],
        pages=[
            SimpleNamespace(
                page_number=index + 1,
                width=612,
                height=792,
                unit="point",
                angle=0,
                words=[
                    SimpleNamespace(
                        content="100.00",
                        polygon=[60, 60, 100, 60, 100, 80, 60, 80],
                        span=SimpleNamespace(offset=index * 6, length=6),
                        confidence=0.99,
                    )
                ],
                lines=[],
                selection_marks=[],
                spans=[SimpleNamespace(offset=index * 6, length=6)],
            )
            for index in range(len(kinds))
        ],
    )
    client = SimpleNamespace(
        begin_analyze_document=lambda *args, **kwargs: SimpleNamespace(
            result=lambda **kwargs: result
        )
    )
    monkeypatch.setattr(adapter, "_client", lambda: client)
    monkeypatch.setattr(azure_di, "with_retries", lambda call: call())
    monkeypatch.setattr(layouts, "get_layout_provider_for_format", lambda *_, **kwargs: adapter)
    block_native_imports(monkeypatch)
    run = runs.create_run(dataset.project, sample_workflow, dataset, admin)
    item = run.items.get()
    layout = layouts.get_or_build_layout(document, run_item=item)
    assert item.input_quality["status"] == "off"
    for index, page in enumerate(layout.pages):
        assert page.has_text_layer == (kinds[index] == "digital")
        capture = {
            "run": run.pk,
            "unit_index": index,
            "field_name": f"total_{index}",
            "text": "100.00",
            "rects": [],
            "page_width_pt": 612,
            "page_height_pt": 792,
            "user": admin,
        }
        if kinds[index] == "digital":
            label = labeling.label_from_pdfjs(document, **capture)
            assert label.azure_span["word_ids"] == [f"p{index + 1}:w0"]
        else:
            with pytest.raises(SpanMappingFailed, match="OCR word selection"):
                labeling.label_from_pdfjs(document, **capture)
    # A provider-only normalization call lacks source inspection and stays conservative.
    assert not any(
        page.has_text_layer
        for page in adapter.normalize(
            result, document_id=str(document.pk), source_format="pdf"
        ).pages
    )
