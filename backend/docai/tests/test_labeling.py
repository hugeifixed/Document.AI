from __future__ import annotations

import pytest

from docai.exceptions import SpanMappingFailed, ValidationFailed
from docai.models import (
    AuditEvent,
    Document,
    ExtractedField,
    GroundTruthLabel,
    ProcessingArtifact,
    ReviewAction,
    SourceSpan,
    SourceUnit,
)
from docai.schemas.layout import LayoutDocument, LayoutPage, LayoutSheet, SheetCell, Span, Word
from docai.services import labeling, runs

pytestmark = pytest.mark.django_db


def test_capture_service_owns_mode_specific_required_fields():
    with pytest.raises(ValidationFailed) as raised:
        labeling.capture_label({"mode": "word_ids", "document": "missing"})

    assert set(raised.value.errors) == {"field_name", "unit_index", "word_ids"}


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


@pytest.fixture
def reviewed_field(project, dataset, admin, sample_workflow):
    document = _document(dataset, name="reviewed.pdf", digest="9" * 64, file_format="pdf")
    run = runs.create_run(project, sample_workflow, dataset, admin)
    artifact = ProcessingArtifact.objects.create(
        document=document, kind="layout", storage_path="layout/first.json", sha256="8" * 64
    )
    unit = SourceUnit.objects.create(
        document=document, layout_artifact=artifact, kind="page", index=2, label="Page 3"
    )
    field = ExtractedField.objects.create(
        document=document,
        run=run,
        name="total",
        field_type="currency",
        raw_value="100",
        reviewed_value="101.00",
        review_status="corrected",
    )
    SourceSpan.objects.create(
        field=field,
        unit=unit,
        text="100",
        offset_start=6,
        offset_end=9,
        word_ids=["p3:w1"],
        polygon=[0.1, 0.2, 0.3, 0.2, 0.3, 0.4, 0.1, 0.4],
        mapping_method="digits",
        match_score=0.95,
        exceptions=["OCR ambiguity"],
        origin="model",
    )
    return field


@pytest.mark.parametrize("kind", ["page", "sheet"])
def test_promoted_label_returns_independent_source_evidence(api, reviewed_field, kind):
    field = reviewed_field
    source = field.spans.get()
    if kind == "sheet":
        source.unit.kind = "sheet"
        source.unit.save(update_fields=["kind"])
        source.cell_range = "B4"
        source.save(update_fields=["cell_range"])
    # A newer representation must not replace this prediction's evidence.
    newer = ProcessingArtifact.objects.create(
        document=field.document, kind="layout", storage_path="layout/new.json", sha256="7" * 64
    )
    SourceUnit.objects.create(
        document=field.document, layout_artifact=newer, kind=kind, index=2, label="New source"
    )
    response = api.post(
        f"/api/v1/fields/{field.pk}/promote/", {"reason": "verified"}, format="json"
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["expected_value"] == data["normalized_value"] == "101.00"
    assert len(data["spans"]) == 1
    assert data["spans"][0]["unit_index"] == 2
    assert data["spans"][0]["text"] == "100"  # Source text is not the corrected assertion.
    label = GroundTruthLabel.objects.get(pk=data["id"])
    evidence = label.spans.get()
    assert evidence.pk != source.pk and evidence.field_id is None
    assert evidence.unit_id == source.unit_id == label.unit_id
    assert evidence.unit.layout_artifact_id != newer.pk
    for attribute in (
        "text",
        "offset_start",
        "offset_end",
        "word_ids",
        "polygon",
        "cell_range",
        "mapping_method",
        "match_score",
        "exceptions",
        "origin",
    ):
        assert getattr(evidence, attribute) == getattr(source, attribute)
    assert label.cell_range == source.cell_range
    assert label.mapping_exceptions == source.exceptions
    assert ReviewAction.objects.filter(field=field, action="promote").count() == 1
    assert AuditEvent.objects.filter(action="review.promote").count() == 1
    source.delete()
    assert label.spans.get().text == "100"


@pytest.mark.parametrize("status", ["absent", "accepted"])
def test_promotion_does_not_invent_evidence(api, reviewed_field, status):
    field = reviewed_field
    if status == "accepted":
        field.spans.all().delete()
    field.review_status = status
    field.reviewed_value = None if status == "absent" else field.raw_value
    field.save(update_fields=["review_status", "reviewed_value"])
    response = api.post(f"/api/v1/fields/{field.pk}/promote/", {}, format="json")
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["spans"] == [] and data["unit"] is None and data["azure_span"] == {}
    assert data["is_absent"] is (status == "absent")


@pytest.mark.parametrize("mode", ["capture", "promotion"])
@pytest.mark.parametrize("failure", ["span", "audit"])
def test_label_creation_rolls_back_evidence_versions_and_audit(
    reviewed_field, admin, monkeypatch, mode, failure
):
    field = reviewed_field
    document = field.document
    # Absence is applicable to every representation and must survive failed publication.
    previous = labeling.label_absent(document, field_name=field.name, user=admin)
    before = (
        GroundTruthLabel.objects.count(),
        SourceSpan.objects.count(),
        ReviewAction.objects.count(),
        AuditEvent.objects.count(),
    )
    monkeypatch.setattr(labeling, "read_artifact_layout", lambda _: _page_layout(document))
    # Capture uses page zero of this layout; promotion uses the existing page-three source.
    SourceUnit.objects.create(
        document=document,
        layout_artifact=field.spans.get().unit.layout_artifact,
        kind="page",
        index=0,
        label="Page 1",
    )

    def fail(*args, **kwargs):
        raise RuntimeError("publication failed")

    manager = SourceSpan.objects if failure == "span" else AuditEvent.objects
    monkeypatch.setattr(manager, "create", fail)
    with pytest.raises(RuntimeError, match="publication failed"):
        if mode == "capture":
            labeling.label_from_word_ids(
                document,
                unit_index=0,
                field_name=field.name,
                expected_value="100",
                word_ids=["p1:w1"],
                user=admin,
            )
        else:
            labeling.promote_field_to_ground_truth(field, admin)
    previous.refresh_from_db()
    assert previous.status == "final" and previous.version == 1
    assert (
        GroundTruthLabel.objects.count(),
        SourceSpan.objects.count(),
        ReviewAction.objects.count(),
        AuditEvent.objects.count(),
    ) == before
