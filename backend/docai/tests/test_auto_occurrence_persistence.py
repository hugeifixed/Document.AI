"""Repeated auto fields survive extraction, persistence, API reads, and visual labels."""

from collections import Counter
from types import SimpleNamespace

import pytest

from docai.models import Document, SourceUnit
from docai.schemas.config import ExtractStructuredConfig
from docai.schemas.layout import (
    LayoutDocument,
    LayoutPage,
    LayoutSheet,
    Line,
    Paragraph,
    SelectionMark,
    SheetCell,
    Span,
    Table,
    TableCell,
    Word,
)
from docai.schemas.llm import StructuredResult
from docai.services import governance, runs
from docai.services.extraction_visualization import collect_labels
from docai.workflows.base import PromptRef, WorkflowContext
from docai.workflows.extract_structured import ExtractStructured

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_artifact_storage(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def _polygon(row):
    y = 0.1 + row * 0.1
    return [0.2, y, 0.4, y, 0.4, y + 0.04, 0.2, y + 0.04]


def _page(index, values, *, table=False):
    page = LayoutPage(index=index, number=index + 1)
    text = []
    offset = 0
    cells = []
    for row, value in enumerate(values):
        line_text = f"Date of Birth {value}"
        word = Word(
            id=f"p{index + 1}:w{row}",
            text=value,
            polygon=_polygon(row),
            span=Span(offset=offset + len("Date of Birth "), length=len(value)),
        )
        page.words.append(word)
        page.lines.append(
            Line(
                id=f"p{index + 1}:l{row}",
                text=line_text,
                polygon=_polygon(row),
                span=Span(offset=offset, length=len(line_text)),
                word_ids=[word.id],
            )
        )
        cells.append(
            TableCell(
                id=f"p{index + 1}:t0:r{row}:c0",
                row=row,
                col=0,
                text=value,
                span=word.span,
                polygon=word.polygon,
            )
        )
        text.append(line_text)
        offset += len(line_text) + 1
    page.content = "\n".join(text)
    if table:
        page.tables = [
            Table(id=f"p{index + 1}:t0", row_count=len(values), col_count=1, cells=cells)
        ]
    return page


def _pair(value, unit_index, source_id, *, name="Date of Birth", confidence=0.91):
    return {
        "name": name,
        "value": value,
        "confidence": confidence,
        "evidence": f"Synthetic record at {source_id}",
        "unit_index": unit_index,
        "sources": [{"unit_index": unit_index, "ids": [source_id]}],
    }


def _extract(layout, predictions, *, chunking=None):
    config = {
        "mode": "default",
        "routing": [{"when": {"min_score": 0}, "outcome": "auto_accept"}],
        "citation_repair": False,
    }
    if chunking:
        config["chunking"] = chunking

    def invoke(call):
        assert call.stage == "generic_kv"
        pairs = predictions(call) if callable(predictions) else predictions
        return StructuredResult(
            parsed=call.schema.model_validate({"pairs": pairs}),
            raw_response="synthetic response",
            model_deployment="fixture",
        )

    context = WorkflowContext(
        workflow_type="extract_structured",
        config=ExtractStructuredConfig.model_validate(config),
        llm=SimpleNamespace(key="fixture", invoke=invoke),
        prompts={"generic_kv": PromptRef("generic_kv", 1, "", "{content}")},
        layout_adapter_key="fixture",
    )
    return ExtractStructured().process_document(context, layout)


def _persist(project, dataset, admin, api, layout, result):
    document = Document.objects.create(
        dataset=dataset,
        original_filename="synthetic-records.xlsx" if layout.sheets else "synthetic-records.pdf",
        mime_type="application/octet-stream",
        file_format=layout.source_format,
        status="validated",
        sha256="a" * 64,
        size_bytes=1,
        storage_path="synthetic-records",
        created_by=admin,
    )
    for unit in layout.units:
        SourceUnit.objects.create(document=document, kind=unit.kind, index=unit.index)
    workflow = governance.create_workflow_version(
        project, "Repeated records", "extract_structured", {"mode": "default"}, admin
    )
    run = runs.create_run(project, workflow, dataset, admin)
    runs.persist_result(run, document, result, layout)
    response = api.get("/api/v1/fields/", {"run": str(run.pk)})
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["count"] == len(result.fields)
    fields = payload["results"]
    assert {field["id"] for field in fields} == {str(field.pk) for field in run.fields.all()}
    assert len({field["id"] for field in fields}) == len(result.fields)
    return run, fields


@pytest.mark.parametrize("same_value", [False, True])
@pytest.mark.parametrize("separate_pages", [False, True])
@pytest.mark.parametrize("citation_kind", ["word", "line", "table_cell"])
def test_repeated_dates_have_independent_fields_spans_and_visual_labels(
    project, dataset, admin, api, same_value, separate_pages, citation_kind
):
    values = ["01/02/70", "01/02/70" if same_value else "03/04/72"]
    pages = (
        [
            _page(index, [value], table=citation_kind == "table_cell")
            for index, value in enumerate(values)
        ]
        if separate_pages
        else [_page(0, values, table=citation_kind == "table_cell")]
    )
    layout = LayoutDocument(
        document_id="synthetic", source_format="pdf", service="fixture", units=pages
    )
    pairs = []
    expected_locations = []
    for index, value in enumerate(values):
        page_index, row = (index, 0) if separate_pages else (0, index)
        page = pages[page_index]
        source_id = {
            "word": page.words[row].id,
            "line": page.lines[row].id,
            "table_cell": f"p{page_index + 1}:t0:r{row}:c0",
        }[citation_kind]
        pairs.append(_pair(value, page_index, source_id))
        expected_locations.append(
            (page_index, tuple(page.words[row].polygon), (page.words[row].id,))
        )

    result = _extract(layout, pairs)
    assert [(field.name, field.raw_value) for field in result.fields] == [
        ("Date of Birth", value) for value in values
    ]
    assert [field.source_text for field in result.fields] == [pair["evidence"] for pair in pairs]
    labels = collect_labels(result, layout)
    assert [label["id"] for label in labels] == ["F001", "F002"]
    assert [label["color"] for label in labels] == ["blue", "blue"]
    assert [
        (
            label["unit_index"],
            tuple(label["grounding"]["polygon"]),
            tuple(label["grounding"]["word_ids"]),
        )
        for label in labels
    ] == expected_locations

    run, fields = _persist(project, dataset, admin, api, layout, result)
    assert Counter(field["raw_value"] for field in fields) == Counter(values)
    assert all(field["name"] == "Date of Birth" and field["grounded"] for field in fields)
    assert all(field["review_status"] == "auto_accepted" for field in fields)
    assert all(field["score"] == 0.91 for field in fields)
    assert sorted(
        (span["unit_index"], tuple(span["polygon"]), tuple(span["word_ids"]))
        for field in fields
        for span in field["spans"]
    ) == sorted(expected_locations)
    assert run.fields.count() == 2


def test_same_cell_reference_on_different_sheets_remains_two_fields(project, dataset, admin, api):
    sheets = [
        LayoutSheet(
            index=index,
            name=f"Record {index + 1}",
            row_count=1,
            col_count=2,
            cells=[SheetCell(id=f"s{index}:B1", ref="B1", row=1, col=2, value="VA")],
        )
        for index in range(2)
    ]
    layout = LayoutDocument(
        document_id="synthetic", source_format="xlsx", service="fixture", units=sheets
    )
    result = _extract(
        layout, [_pair("VA", index, f"s{index}:B1", name="State") for index in range(2)]
    )
    assert len(result.fields) == 2
    labels = collect_labels(result, layout)
    assert [label["grounding"]["word_ids"] for label in labels] == [["s0:B1"], ["s1:B1"]]
    assert [label["grounding"]["cell_range"] for label in labels] == ["B1", "B1"]
    _, fields = _persist(project, dataset, admin, api, layout, result)
    assert sorted(
        (span["unit_index"], span["cell_range"], tuple(span["word_ids"]))
        for field in fields
        for span in field["spans"]
    ) == [(0, "B1", ("s0:B1",)), (1, "B1", ("s1:B1",))]


def test_real_context_overlap_deduplicates_one_occurrence_without_erasing_another(
    project, dataset, admin, api
):
    page = _page(0, ["VA", "VA"])
    target_lines = page.lines
    lines = []
    for index in range(48):
        if index in (12, 28):
            lines.append(target_lines[0 if index == 12 else 1])
        else:
            lines.append(
                Line(
                    id=f"p1:l{index + 2}",
                    text=f"Synthetic filler {index:02} " + "x" * 70,
                    polygon=[],
                )
            )
    # Row-band rendering omits unboxed filler; use paragraphs to retain all lines.
    page.lines = []
    page.paragraphs = [
        Paragraph(id=line.id, text=line.text, span=line.span, polygon=line.polygon)
        for line in lines
    ]
    page.reading_order = [paragraph.id for paragraph in page.paragraphs]
    layout = LayoutDocument(
        document_id="synthetic", source_format="pdf", service="fixture", units=[page]
    )
    predicted: Counter[int] = Counter()

    def predictions(call):
        pairs = []
        for row, line in enumerate(target_lines):
            if f"{line.text}  [{line.id}]" in call.user:
                predicted[row] += 1
                pairs.append(
                    _pair("VA", 0, line.id, name=" State " if call.chunk_index == 0 else "STATE")
                )
        return pairs

    result = _extract(
        layout,
        predictions,
        chunking={"strategy": "context_length", "chunk_chars": 2000, "overlap_chars": 600},
    )
    assert result.extraction_chunks >= 3
    assert predicted[0] >= 1 and predicted[1] >= 1 and sum(predicted.values()) > 2
    assert len(result.fields) == 2
    labels = collect_labels(result, layout)
    assert {tuple(label["grounding"]["word_ids"]) for label in labels} == {("p1:w0",), ("p1:w1",)}
    _, fields = _persist(project, dataset, admin, api, layout, result)
    assert len(fields) == 2
    assert len({span["id"] for field in fields for span in field["spans"]}) == 2


@pytest.mark.parametrize("invalid_first", [False, True])
def test_invalid_repeated_label_retains_own_review_and_never_inherits_neighbor_geometry(
    project, dataset, admin, api, invalid_first
):
    layout = LayoutDocument(
        document_id="synthetic",
        source_format="pdf",
        service="fixture",
        units=[_page(0, ["01/02/70"])],
    )
    valid = _pair("01/02/70", 0, "p1:l0", confidence=0.96)
    invalid = _pair("01/02/70", 0, "p1:missing", confidence=None)
    pairs = [invalid, valid] if invalid_first else [valid, invalid]
    result = _extract(layout, pairs)
    assert len(result.fields) == 2
    good, bad = (result.fields[1], result.fields[0]) if invalid_first else result.fields
    assert good.grounding is not None and good.score == 0.96
    assert bad.grounding is None and bad.score is None
    assert bad.validation_status == "failed" and bad.review_outcome == "human_review"
    assert bad.source_text == invalid["evidence"]
    labels = collect_labels(result, layout)
    assert Counter(label["color"] for label in labels) == {"blue": 1, "orange": 1}
    assert next(label for label in labels if label["color"] == "orange")["grounding"] is None
    _, fields = _persist(project, dataset, admin, api, layout, result)
    good = next(field for field in fields if field["grounded"])
    bad = next(field for field in fields if not field["grounded"])
    assert good["score"] == 0.96 and len(good["spans"]) == 1
    assert bad["score"] is None and bad["spans"] == []
    assert bad["validation_status"] == "failed" and bad["review_status"] == "needs_review"


def test_same_label_same_state_checkboxes_keep_independent_mark_spans(project, dataset, admin, api):
    page = LayoutPage(
        index=0,
        number=1,
        selection_marks=[
            SelectionMark(id=f"p1:sm{index}", state="selected", polygon=_polygon(index))
            for index in range(2)
        ],
    )
    layout = LayoutDocument(
        document_id="synthetic", source_format="pdf", service="fixture", units=[page]
    )
    result = _extract(
        layout, [_pair("selected", 0, mark.id, name="Consent") for mark in page.selection_marks]
    )
    assert len(result.fields) == 2
    labels = collect_labels(result, layout)
    assert [label["grounding"]["word_ids"] for label in labels] == [["p1:sm0"], ["p1:sm1"]]
    _, fields = _persist(project, dataset, admin, api, layout, result)
    assert {tuple(span["word_ids"]) for field in fields for span in field["spans"]} == {
        ("p1:sm0",),
        ("p1:sm1",),
    }
    assert all(
        span["mapping_method"] == "selection_mark" for field in fields for span in field["spans"]
    )
