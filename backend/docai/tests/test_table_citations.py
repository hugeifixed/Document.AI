"""Merged positions cite real cells through rendering, chunking and grounding."""

import re
from types import SimpleNamespace

import pytest

from docai.exceptions import InvalidModelOutput
from docai.grounding.sources import validate_sources
from docai.layout.chunk import plan_chunks
from docai.layout.preserve import preserve_page
from docai.schemas.config import ChunkingConfig, ExtractStructuredConfig, LayoutPreservationConfig
from docai.schemas.layout import LayoutDocument, LayoutPage, Span, Table, TableCell, Word
from docai.schemas.llm import FieldOut, SourceRef, StructuredResult
from docai.workflows.base import PromptRef, WorkflowContext
from docai.workflows.extract_structured import ExtractStructured
from docai.workflows.extraction_core import ground


@pytest.fixture
def merged_page():
    return LayoutPage(
        index=2,
        number=3,
        content="100",
        words=[
            Word(
                id="p3:w0",
                text="100",
                span=Span(offset=0, length=3),
                polygon=[0.1, 0.1, 0.2, 0.1, 0.2, 0.2, 0.1, 0.2],
            )
        ],
        tables=[
            Table(
                id="p3:t0",
                row_count=2,
                col_count=2,
                cells=[
                    TableCell(
                        id="p3:t0:r0:c0",
                        row=0,
                        col=0,
                        row_span=2,
                        col_span=2,
                        text="100",
                        span=Span(offset=0, length=3),
                    )
                ],
            )
        ],
    )


def test_every_merged_position_reuses_original_id_without_mutating_layout(merged_page):
    before = merged_page.model_dump()
    text = preserve_page(merged_page, LayoutPreservationConfig())
    assert text.count("100 [p3:t0:r0:c0]") == 4
    assert set(re.findall(r"\[(p\d+:t\d+:r\d+:c\d+)\]", text)) == {"p3:t0:r0:c0"}
    assert "[cells " not in text
    assert merged_page.model_dump() == before
    without_ids = preserve_page(merged_page, LayoutPreservationConfig(include_source_ids=False))
    assert "p3:t0:r0:c0" not in without_ids
    assert "| 100 | 100 |" in without_ids


def test_large_tables_keep_late_cell_citations_and_escape_text():
    page = LayoutPage(
        index=0,
        number=1,
        tables=[
            Table(
                id="p1:t0",
                row_count=70,
                col_count=1,
                cells=[
                    TableCell(
                        id=f"p1:t0:r{row}:c0",
                        row=row,
                        col=0,
                        text="Alpha|Beta\nGamma" if row == 69 else str(row),
                    )
                    for row in range(70)
                ],
            )
        ],
    )
    text = preserve_page(page, LayoutPreservationConfig())
    assert "Alpha\\|Beta Gamma [p1:t0:r69:c0]" in text
    assert len(re.findall(r"\[p1:t0:r\d+:c0\]", text)) == 70


def test_large_table_fallback_keeps_inline_ids_in_overlapping_chunks():
    cells = [
        TableCell(id=f"p1:t0:r{row}:c0", row=row, col=0, text=f"Line item {row}: " + "detail " * 12)
        for row in range(70)
    ]
    page = LayoutPage(
        index=0, number=1, tables=[Table(id="p1:t0", row_count=70, col_count=1, cells=cells)]
    )
    text = preserve_page(page, LayoutPreservationConfig())
    plan = plan_chunks(
        [text], ChunkingConfig(whole_document_max_chars=2000, chunk_chars=2000, overlap_chars=256)
    )
    assert plan.strategy_used == "context_length" and plan.fallback_used
    assert len(plan.chunks) > 1
    actual_ids = set()
    for chunk in plan.chunks:
        assert chunk.unit_indexes == [0]
        assert "=== PAGE 1 (unit 0) ===" in chunk.text
        actual_ids.update(re.findall(r"\[(p\d+:t\d+:r\d+:c\d+)\]", chunk.text))
    assert actual_ids == {cell.id for cell in cells}


@pytest.mark.parametrize("strategy", ["whole_document", "page", "context_length", "semantic"])
def test_chunks_preserve_merged_citations_and_original_page_identity(merged_page, strategy):
    text = preserve_page(merged_page, LayoutPreservationConfig())
    plan = plan_chunks(
        ["", "", text], ChunkingConfig(strategy=strategy), excluded_unit_indexes={0, 1}
    )
    layout = LayoutDocument(
        document_id="merged", source_format="pdf", service="fixture", units=[merged_page]
    )
    for chunk in plan.chunks:
        assert chunk.unit_indexes == [2]
        assert "=== PAGE 3 (unit 2) ===" in chunk.text
        ids = re.findall(r"\[(p\d+:t\d+:r\d+:c\d+)\]", chunk.text)
        assert ids == ["p3:t0:r0:c0"] * 4
        validate_sources(
            layout, [SourceRef(unit_index=2, ids=ids)], allowed_indexes=set(chunk.unit_indexes)
        )
    field = FieldOut(
        name="total",
        value="100",
        unit_index=2,
        sources=[SourceRef(unit_index=2, ids=["p3:t0:r0:c0"])],
    )
    hit = ground(layout, field, 2)
    assert hit is not None and hit["unit_index"] == 2 and hit["word_ids"] == ["p3:w0"]
    assert hit["polygon"] == merged_page.words[0].polygon
    invented = field.model_copy(update={"sources": [SourceRef(unit_index=2, ids=["p3:t0:r1:c1"])]})
    with pytest.raises(InvalidModelOutput):
        validate_sources(layout, invented.sources)
    assert ground(layout, invented, 2) is None


@pytest.mark.parametrize("mode", ["default", "custom"])
def test_extraction_uses_inline_citation_without_changing_value(merged_page, mode):
    def invoke(call):
        assert "never derive IDs from displayed row or column positions" in call.system
        match = re.search(r"(100) \[(p3:t0:r0:c0)\]", call.user)
        assert match is not None
        value, source_id = match.groups()
        return StructuredResult(
            parsed=call.schema.model_validate(
                {
                    "pairs" if mode == "default" else "fields": [
                        {
                            "name": "total",
                            "value": value,
                            "confidence": 1,
                            "unit_index": 2,
                            "sources": [{"unit_index": 2, "ids": [source_id]}],
                        }
                    ],
                }
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    ctx = WorkflowContext(
        workflow_type="extract_structured",
        config=ExtractStructuredConfig.model_validate(
            {"mode": mode, "schema": {"name": "totals", "fields": [{"name": "total"}]}}
        ),
        llm=SimpleNamespace(key="fixture", invoke=invoke),
        layout_adapter_key="fixture",
        prompts={
            stage: PromptRef(stage, 1, "", "{content}") for stage in ["generic_kv", "extraction"]
        },
    )
    layout = LayoutDocument(
        document_id="merged",
        source_format="pdf",
        service="fixture",
        units=[LayoutPage(index=i, number=i + 1, excluded_from_analysis=True) for i in range(2)]
        + [merged_page],
    )
    result = ExtractStructured().process_document(ctx, layout)
    field = result.fields[0]
    assert field.raw_value == "100" and field.normalized_value == "100"
    assert field.grounding is not None and field.grounding["unit_index"] == 2
    assert field.review_outcome == "auto_accept" and not result.warnings
