from __future__ import annotations

import pytest

from docai.exceptions import SpanMappingFailed
from docai.models import Document, GroundTruthLabel, SourceSpan, SourceUnit
from docai.schemas.layout import LayoutDocument, LayoutPage, LayoutSheet, SheetCell, Span, Word
from docai.services import labeling

pytestmark = pytest.mark.django_db


def _document(dataset, *, name: str, digest: str, file_format: str) -> Document:
    return Document.objects.create(
        dataset=dataset,
        original_filename=name,
        mime_type="application/octet-stream",
        file_format=file_format,
        sha256=digest,
        size_bytes=256,
        storage_path=f"documents/{name}",
    )


def _page_layout(document: Document) -> LayoutDocument:
    return LayoutDocument(
        document_id=str(document.id),
        source_format="pdf",
        service="fixture",
        units=[
            LayoutPage(
                index=0,
                number=1,
                width=100,
                height=100,
                content="Total 100",
                words=[
                    Word(
                        id="p1:w0",
                        text="Total",
                        polygon=[0.1, 0.1, 0.3, 0.1, 0.3, 0.2, 0.1, 0.2],
                        span=Span(offset=0, length=5),
                    ),
                    Word(
                        id="p1:w1",
                        text="100",
                        polygon=[0.35, 0.1, 0.5, 0.1, 0.5, 0.2, 0.35, 0.2],
                        span=Span(offset=6, length=3),
                    ),
                ],
            )
        ],
    )


def test_pdf_and_word_box_labels_keep_source_evidence_and_versions(dataset, admin, monkeypatch):
    document = _document(dataset, name="invoice.pdf", digest="b" * 64, file_format="pdf")
    SourceUnit.objects.create(document=document, kind="page", index=0, label="Page 1")
    layout = _page_layout(document)
    monkeypatch.setattr(labeling, "load_layout", lambda _document: layout)

    first = labeling.label_from_pdfjs(
        document,
        unit_index=0,
        field_name="total",
        expected_value="100",
        text="100",
        rects=[{"x": 35, "y": 80, "width": 15, "height": 10}],
        page_width_pt=100,
        page_height_pt=100,
        user=admin,
    )
    second = labeling.label_from_word_ids(
        document,
        unit_index=0,
        field_name="total",
        expected_value="100.00",
        word_ids=["p1:w1"],
        field_type="currency",
        user=admin,
    )

    first.refresh_from_db()
    assert first.status == "superseded"
    assert second.version == 2
    assert second.normalized_value == "100.00"
    assert second.azure_span["word_ids"] == ["p1:w1"]
    assert SourceSpan.objects.get(label=first).origin == "pdfjs"
    assert SourceSpan.objects.get(label=second).text == "100"


def test_spreadsheet_label_preserves_cells_formulas_and_empty_ranges(dataset, admin, monkeypatch):
    document = _document(dataset, name="ledger.xlsx", digest="c" * 64, file_format="xlsx")
    SourceUnit.objects.create(document=document, kind="sheet", index=0, label="Ledger")
    layout = LayoutDocument(
        document_id=str(document.id),
        source_format="xlsx",
        service="fixture",
        units=[
            LayoutSheet(
                index=0,
                name="Ledger",
                row_count=2,
                col_count=2,
                cells=[
                    SheetCell(id="s0:A1", ref="A1", row=1, col=1, value="Net"),
                    SheetCell(id="s0:B1", ref="B1", row=1, col=2, value="42", formula="=SUM(B2)"),
                ],
            )
        ],
    )
    monkeypatch.setattr(labeling, "load_layout", lambda _document: layout)

    populated = labeling.label_from_cells(
        document,
        unit_index=0,
        field_name="net",
        expected_value="42",
        cell_range="A1:B1",
        user=admin,
    )
    empty = labeling.label_from_cells(
        document,
        unit_index=0,
        field_name="tax",
        expected_value="",
        cell_range="C9",
        user=admin,
    )

    assert populated.azure_span["displayed_value"] == "Net 42"
    assert populated.azure_span["formulas"] == {"B1": "=SUM(B2)"}
    assert populated.match_score == 1.0
    assert empty.match_score == 0.0
    assert empty.mapping_exceptions == ["range has no populated cells"]
    assert labeling._expand_range("bad range") == {"BAD RANGE"}


def test_relabeling_a_document_category_supersedes_the_previous_truth(dataset, admin):
    document = _document(dataset, name="unknown.pdf", digest="d" * 64, file_format="pdf")

    first = labeling.label_category(document, category="other", user=admin)
    second = labeling.label_category(document, category="bank-statement", user=admin)

    first.refresh_from_db()
    assert first.status == "superseded"
    assert second.version == 2
    assert second.status == "final"
    assert GroundTruthLabel.objects.filter(document=document, status="final").count() == 1


def test_relabeling_a_segment_range_versions_only_that_range(dataset, admin):
    document = _document(dataset, name="bundle.pdf", digest="1" * 64, file_format="pdf")

    first = labeling.label_category(
        document, category="invoice", segment_start=0, segment_end=1, user=admin
    )
    other = labeling.label_category(
        document, category="receipt", segment_start=2, segment_end=2, user=admin
    )
    revised = labeling.label_category(
        document, category="statement", segment_start=0, segment_end=1, user=admin
    )

    first.refresh_from_db()
    other.refresh_from_db()
    assert (first.status, revised.version) == ("superseded", 2)
    assert (other.status, other.version) == ("final", 1)


def test_labeling_rejects_missing_layout_wrong_unit_type_and_unknown_words(dataset, monkeypatch):
    document = _document(dataset, name="scan.pdf", digest="e" * 64, file_format="pdf")
    SourceUnit.objects.create(document=document, kind="page", index=0, label="Page 1")

    monkeypatch.setattr(labeling, "load_layout", lambda _document: None)
    with pytest.raises(SpanMappingFailed, match="No layout"):
        labeling.label_from_word_ids(
            document,
            unit_index=0,
            field_name="account",
            expected_value="1",
            word_ids=["missing"],
        )

    page_layout = _page_layout(document)
    monkeypatch.setattr(labeling, "load_layout", lambda _document: page_layout)
    with pytest.raises(SpanMappingFailed) as exc:
        labeling.label_from_word_ids(
            document,
            unit_index=0,
            field_name="account",
            expected_value="1",
            word_ids=["missing"],
        )
    assert exc.value.errors == {"word_ids": "unknown ids"}

    sheet_layout = LayoutDocument(
        document_id=str(document.id),
        source_format="xlsx",
        service="fixture",
        units=[LayoutSheet(index=0, name="Sheet1", row_count=0, col_count=0)],
    )
    monkeypatch.setattr(labeling, "load_layout", lambda _document: sheet_layout)
    with pytest.raises(SpanMappingFailed, match="pages, not worksheets"):
        labeling.label_from_word_ids(
            document,
            unit_index=0,
            field_name="account",
            expected_value="1",
            word_ids=["p1:w0"],
        )


def test_label_api_supports_each_source_selection_mode(api, dataset, monkeypatch):
    page_document = _document(dataset, name="api-invoice.pdf", digest="f" * 64, file_format="pdf")
    SourceUnit.objects.create(document=page_document, kind="page", index=0, label="Page 1")
    monkeypatch.setattr(labeling, "load_layout", lambda _document: _page_layout(page_document))

    pdfjs = api.post(
        "/api/v1/labels/",
        {
            "document": str(page_document.id),
            "mode": "pdfjs",
            "field_name": "total",
            "expected_value": "100",
            "text": "100",
            "unit_index": 0,
            "rects": [{"x": 35, "y": 80, "width": 15, "height": 10}],
            "page_width_pt": 100,
            "page_height_pt": 100,
        },
        format="json",
    )
    word_ids = api.post(
        "/api/v1/labels/",
        {
            "document": str(page_document.id),
            "mode": "word_ids",
            "field_name": "subtotal",
            "expected_value": "100",
            "unit_index": 0,
            "word_ids": ["p1:w1"],
        },
        format="json",
    )

    sheet_document = _document(dataset, name="api-ledger.xlsx", digest="0" * 64, file_format="xlsx")
    SourceUnit.objects.create(document=sheet_document, kind="sheet", index=0, label="Ledger")
    sheet_layout = LayoutDocument(
        document_id=str(sheet_document.id),
        source_format="xlsx",
        service="fixture",
        units=[
            LayoutSheet(
                index=0,
                name="Ledger",
                row_count=1,
                col_count=1,
                cells=[SheetCell(id="s0:A1", ref="A1", row=1, col=1, value="42")],
            )
        ],
    )
    monkeypatch.setattr(labeling, "load_layout", lambda _document: sheet_layout)
    cells = api.post(
        "/api/v1/labels/",
        {
            "document": str(sheet_document.id),
            "mode": "cells",
            "field_name": "net",
            "expected_value": "42",
            "unit_index": 0,
            "cell_range": "A1",
        },
        format="json",
    )

    assert pdfjs.status_code == word_ids.status_code == cells.status_code == 201
    assert pdfjs.json()["data"]["mapping_method"]
    assert word_ids.json()["data"]["azure_span"]["word_ids"] == ["p1:w1"]
    assert cells.json()["data"]["azure_span"]["cell_range"] == "A1"
