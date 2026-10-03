"""Partial tables must not hide neighboring or interleaved source text."""

import re
from types import SimpleNamespace

import pytest

from docai.grounding.sources import validate_sources
from docai.layout.preserve import preserve, preserve_page
from docai.schemas.config import ExtractStructuredConfig, LayoutPreservationConfig
from docai.schemas.layout import (
    LayoutDocument,
    LayoutPage,
    Line,
    Paragraph,
    SelectionMark,
    Span,
    Table,
    TableCell,
    Word,
)
from docai.schemas.llm import FieldOut, SourceRef, StructuredResult
from docai.workflows.base import PromptRef, WorkflowContext
from docai.workflows.evidence import ground
from docai.workflows.extract_structured import ExtractStructured


def _page(rows: list[list[tuple[str, int | None]]], *, index: int = 0) -> LayoutPage:
    """Each entry is (text, table number or None); offsets follow OCR order."""
    page = LayoutPage(index=index, number=index + 1)
    tables: dict[int, Table] = {}
    prefix = f"p{index + 1}"
    for row_index, row in enumerate(rows):
        for col_index, (text, table_number) in enumerate(row):
            span = Span(offset=len(page.content), length=len(text))
            polygon = [
                col_index * 0.3,
                row_index * 0.1,
                col_index * 0.3 + 0.2,
                row_index * 0.1,
                col_index * 0.3 + 0.2,
                row_index * 0.1 + 0.02,
                col_index * 0.3,
                row_index * 0.1 + 0.02,
            ]
            source_number = len(page.lines)
            word = Word(id=f"{prefix}:w{source_number}", text=text, span=span, polygon=polygon)
            page.words.append(word)
            page.lines.append(
                Line(
                    id=f"{prefix}:l{source_number}",
                    text=text,
                    span=span,
                    polygon=polygon,
                    word_ids=[word.id],
                )
            )
            page.paragraphs.append(
                Paragraph(id=f"{prefix}:para{source_number}", text=text, span=span)
            )
            page.content += text + "\n"
            if table_number is not None:
                table = tables.setdefault(
                    table_number,
                    Table(id=f"{prefix}:t{table_number}", row_count=0, col_count=1, cells=[]),
                )
                table.cells.append(
                    TableCell(
                        id=f"{table.id}:r{table.row_count}:c0",
                        row=table.row_count,
                        col=0,
                        text=text,
                        span=span,
                    )
                )
                table.row_count += 1
    page.tables = list(tables.values())
    page.reading_order = [p.id for p in page.paragraphs] + [t.id for t in page.tables]
    return page


@pytest.mark.parametrize("position", ["left", "right", "both"])
@pytest.mark.parametrize("link_rows", [True, False])
def test_partial_tables_keep_all_neighboring_text_and_only_render_cells_once(position, link_rows):
    rows: list[list[tuple[str, int | None]]] = []
    for value in ["SKU-42", "SKU-73"]:
        row: list[tuple[str, int | None]] = [(value, 0)]
        if position in {"left", "both"}:
            row.insert(0, (f"Manufacturer {value}", None))
        if position in {"right", "both"}:
            row.append((f"Warehouse {value}", None))
        rows.append(row)
    page = _page(rows)
    before = page.model_dump()
    text = preserve_page(page, LayoutPreservationConfig(link_row_bands=link_rows))
    for line, paragraph in zip(page.lines, page.paragraphs, strict=True):
        if line.text.startswith(("Manufacturer", "Warehouse")):
            assert line.text in text
            assert (line.id if link_rows else paragraph.id) in text
        else:
            assert f"{line.text} [p1:t0:" in text
            assert (line.id if link_rows else paragraph.id) not in text
    assert text.count("[table p1:t0]") == 1
    assert page.model_dump() == before


@pytest.mark.parametrize("link_rows", [True, False])
def test_text_in_a_gap_between_cell_spans_is_not_table_content(link_rows):
    page = _page([[("Apples", 0)], [("Delivery instructions: side door", None)], [("Pears", 0)]])
    text = preserve_page(page, LayoutPreservationConfig(link_row_bands=link_rows))
    assert "Delivery instructions: side door" in text
    assert ("p1:l1" if link_rows else "p1:para1") in text
    assert text.count("[table p1:t0]") == 1


def test_two_tables_in_one_band_are_emitted_in_place_and_keep_neighbors():
    page = _page(
        [
            [("Temperature", 0), ("Ambient", None), ("Pressure", 1)],
            [("Packing instructions", None)],
            [("20 C", 0), ("Inspection required", None), ("101 kPa", 1)],
        ]
    )
    text = preserve_page(page, LayoutPreservationConfig())
    assert text.index("[table p1:t0]") < text.index("Packing instructions")
    assert text.index("[table p1:t1]") < text.index("Packing instructions")
    assert "Ambient" in text and "Inspection required" in text
    assert text.count("[table p1:t0]") == text.count("[table p1:t1]") == 1


@pytest.mark.parametrize("link_rows", [True, False])
@pytest.mark.parametrize("gap", ["\n", "\t  ", " special handling "])
def test_a_line_or_paragraph_spanning_cells_only_skips_proven_whitespace_gaps(link_rows, gap):
    page = _page([[("Red", 0)], [("Blue", 0)]])
    page.content = f"Red{gap}Blue"
    page.tables[0].cells[1].span = Span(offset=3 + len(gap), length=4)
    page.lines = [
        Line(
            id="p1:l0",
            text=page.content,
            span=Span(offset=0, length=len(page.content)),
            polygon=page.lines[0].polygon,
        )
    ]
    page.paragraphs = [Paragraph(id="p1:para0", text=page.content, span=page.lines[0].span)]
    page.reading_order = ["p1:para0", "p1:t0"]
    text = preserve_page(page, LayoutPreservationConfig(link_row_bands=link_rows))
    assert (("p1:l0" if link_rows else "p1:para0") in text) == bool(gap.strip())
    assert "Red [p1:t0:r0:c0]" in text and "Blue [p1:t0:r1:c0]" in text


@pytest.mark.parametrize("link_rows", [True, False])
@pytest.mark.parametrize("missing", ["line_span", "cell_span", "zero_length", "content"])
def test_uncertain_span_coverage_preserves_text(link_rows, missing):
    page = _page([[("Red", 0)], [("Blue", 0)]])
    page.lines = [
        Line(
            id="p1:l0",
            text="Red Blue",
            span=Span(offset=0, length=8),
            polygon=page.lines[0].polygon,
        )
    ]
    page.paragraphs = [Paragraph(id="p1:para0", text="Red Blue", span=page.lines[0].span)]
    page.reading_order = ["p1:para0", "p1:t0"]
    if missing == "line_span":
        page.lines[0].span = page.paragraphs[0].span = None
    elif missing == "cell_span":
        page.tables[0].cells[1].span = None
    elif missing == "zero_length":
        page.lines[0].span = page.paragraphs[0].span = Span(offset=0, length=0)
    else:
        page.content = ""
    text = preserve_page(page, LayoutPreservationConfig(link_row_bands=link_rows))
    assert "Red Blue" in text
    assert ("p1:l0" if link_rows else "p1:para0") in text


def test_adjacent_span_boundary_is_not_table_membership():
    page = _page([[("AB", 0), ("Adjacent", None)]])
    page.lines[1].span = Span(offset=2, length=8)
    text = preserve_page(page, LayoutPreservationConfig())
    assert "Adjacent" in text and "p1:l1" in text


def test_restored_evidence_keeps_original_page_and_line_identity_with_repeated_text():
    pages = [_page([[("Zone 7", None), ("Paid", 0)]], index=i) for i in range(3)]
    pages[1].excluded_from_analysis = True
    pages[2].selection_marks = [SelectionMark(id="p3:sm0", state="unselected")]
    layout = LayoutDocument(
        document_id="shipping", source_format="pdf", service="fixture", units=pages
    )
    rendered = preserve(layout)
    assert rendered[1] == ""
    assert "[checkbox p3:sm0: unselected]" in rendered[2]
    for index in [0, 2]:
        line = pages[index].lines[0]
        assert line.id in rendered[index]
        source = SourceRef(unit_index=index, ids=[line.id])
        validate_sources(layout, [source], allowed_indexes={index})
        hit = ground(
            layout, FieldOut(name="zone", value="Zone 7", unit_index=index, sources=[source]), index
        )
        assert hit is not None
        assert hit["unit_index"] == index and hit["word_ids"] == line.word_ids
        assert hit["polygon"] == line.polygon
    without_ids = preserve(layout, LayoutPreservationConfig(include_source_ids=False))
    assert "Zone 7" in without_ids[0] and "Zone 7" in without_ids[2]
    assert not re.search(r"p\d+:l\d+", "\n".join(without_ids))


@pytest.mark.parametrize("mode", ["default", "custom"])
def test_extraction_receives_and_grounds_the_text_beside_a_partial_table(mode):
    page = _page([[("Zone 7", None), ("Paid", 0)]])
    layout = LayoutDocument(
        document_id="shipping", source_format="pdf", service="fixture", units=[page]
    )

    def invoke(call):
        assert "Zone 7  [p1:l0]" in call.user
        assert "Paid [p1:t0:r0:c0]" in call.user
        return StructuredResult(
            parsed=call.schema.model_validate(
                {
                    "pairs" if mode == "default" else "fields": [
                        {
                            "name": "zone",
                            "value": "Zone 7",
                            "confidence": 1,
                            "unit_index": 0,
                            "sources": [{"unit_index": 0, "ids": ["p1:l0"]}],
                        }
                    ]
                }
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    ctx = WorkflowContext(
        workflow_type="extract_structured",
        config=ExtractStructuredConfig.model_validate(
            {"mode": mode, "schema": {"name": "shipping", "fields": [{"name": "zone"}]}}
        ),
        llm=SimpleNamespace(key="fixture", invoke=invoke),
        layout_adapter_key="fixture",
        prompts={
            stage: PromptRef(stage, 1, "", "{content}") for stage in ["generic_kv", "extraction"]
        },
    )
    result = ExtractStructured().process_document(ctx, layout)
    assert len(result.fields) == 1 and not result.warnings
    assert result.fields[0].raw_value == "Zone 7"
    assert result.fields[0].grounding is not None
    assert result.fields[0].grounding["word_ids"] == ["p1:w0"]
