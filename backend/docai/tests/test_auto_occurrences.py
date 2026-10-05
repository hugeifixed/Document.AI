"""Auto extraction must distinguish source occurrences from repeated field names."""

from types import SimpleNamespace

import pytest

from docai.layout.chunk import plan_chunks
from docai.layout.preserve import preserve
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
from docai.workflows.base import PromptRef, WorkflowContext
from docai.workflows.extract_structured import ExtractStructured


def box(row):
    y = 0.05 + (row % 12) * 0.06
    return [0.4, y, 0.6, y, 0.6, y + 0.04, 0.4, y + 0.04]


def page(values, index=0):
    """One row per value, with equivalent word/line/paragraph/table-cell sources."""
    prefix = f"p{index + 1}"
    content = ""
    words, lines, paragraphs, cells = [], [], [], []
    for row, value in enumerate(values):
        text = f"Date of Birth {value}"
        span = Span(offset=len(content) + len("Date of Birth "), length=len(value))
        word = Word(id=f"{prefix}:w{row}", text=value, span=span, polygon=box(row))
        whole = Span(offset=len(content), length=len(text))
        words.append(word)
        lines.append(
            Line(id=f"{prefix}:l{row}", text=text, span=whole, polygon=box(row), word_ids=[word.id])
        )
        paragraphs.append(Paragraph(id=f"{prefix}:p{row}", text=text, span=whole, polygon=box(row)))
        cells.append(TableCell(id=f"{prefix}:t0:r{row}:c0", row=row, col=0, text=value, span=span))
        content += text + "\n"
    return LayoutPage(
        index=index,
        number=index + 1,
        content=content,
        words=words,
        lines=lines,
        paragraphs=paragraphs,
        tables=[Table(id=f"{prefix}:t0", row_count=len(values), col_count=1, cells=cells)],
    )


def document(*units):
    return LayoutDocument(
        document_id="synthetic", source_format="pdf", service="fixture", units=units
    )


def pair(value, source=None, *, name="Date of Birth", index=0, confidence=0.9, **extra):
    return {
        "name": name,
        "value": value,
        "confidence": confidence,
        "unit_index": index,
        "sources": [{"unit_index": index, "ids": [source]}] if source else [],
        **extra,
    }


def extract(doc, responses, *, repairs=None, **config):
    calls = []

    def invoke(call):
        calls.append(call)
        return StructuredResult(
            parsed=call.schema.model_validate(
                {"repairs": repairs or []}
                if call.stage == "citation_repair"
                else {"pairs": responses[call.chunk_index]}
            ),
            raw_response="synthetic response",
            model_deployment="fixture",
        )

    ctx = WorkflowContext(
        workflow_type="extract_structured",
        config=ExtractStructuredConfig.model_validate(
            {
                "mode": "default",
                "routing": [{"when": {"min_score": 0}, "outcome": "auto_accept"}],
                **config,
            }
        ),
        llm=SimpleNamespace(key="synthetic", invoke=invoke),
        prompts={"generic_kv": PromptRef("generic_kv", 1, "", "{content}")},
        layout_adapter_key="fixture",
    )
    return ExtractStructured().process_document(ctx, doc), calls


@pytest.mark.parametrize("values", [("01/03/80", "04/09/82"), ("01/03/80", "01/03/80")])
def test_same_label_at_distinct_positions_retains_each_value_and_evidence(values):
    pairs = [
        pair(value, f"p1:w{row}", confidence=0.8 + row * 0.1) for row, value in enumerate(values)
    ]
    result, calls = extract(document(page(values)), [pairs])
    assert [field.raw_value for field in result.fields] == list(values)
    assert [field.name for field in result.fields] == ["Date of Birth", "Date of Birth"]
    assert [field.score for field in result.fields] == [0.8, 0.9]
    assert [field.grounding["word_ids"] for field in result.fields] == [["p1:w0"], ["p1:w1"]]
    assert all(field.review_outcome == "auto_accept" for field in result.fields)
    assert len(calls) == 1


@pytest.mark.parametrize("same_value", [False, True])
def test_same_label_on_distinct_pages_survives_page_chunks(same_value):
    values = ["100", "100" if same_value else "200"]
    doc = document(*(page([value], index=index) for index, value in enumerate(values)))
    responses = [
        [pair(value, f"p{index + 1}:w0", index=index)] for index, value in enumerate(values)
    ]
    result, _ = extract(doc, responses, chunking={"strategy": "page"})
    assert len(result.fields) == 2
    assert [field.grounding["unit_index"] for field in result.fields] == [0, 1]


@pytest.mark.parametrize("source", ["p1:w0", "p1:l0", "p1:p0", "p1:t0:r0:c0", "p1:t0"])
def test_alternative_citations_of_one_occurrence_are_deduplicated(source):
    first = pair("100", "p1:w0", name=" Date  of Birth ", confidence=0.8)
    repeat = pair("100", source, name="date of birth", confidence=0.99)
    result, _ = extract(document(page(["100"])), [[first, repeat]])
    assert len(result.fields) == 1
    assert result.fields[0].name == "Date  of Birth"
    assert result.fields[0].score == 0.8


@pytest.mark.parametrize("value", [None, "", "100", " 100", "100 "])
def test_missing_location_or_distinct_raw_value_is_retained(value):
    result, _ = extract(
        document(page(["100"])),
        [[pair("100", "p1:w0"), pair(value, None)]],
    )
    assert [field.raw_value for field in result.fields] == ["100", value]


@pytest.mark.parametrize("invalid_first", [False, True])
def test_invalid_same_name_and_value_never_borrows_valid_neighbor_trust(invalid_first):
    candidates = [pair("100", "p1:w0"), pair("100", "p1:invented")]
    if invalid_first:
        candidates.reverse()
    result, _ = extract(document(page(["100"])), [candidates])
    assert len(result.fields) == 2
    good, bad = result.fields[::-1] if invalid_first else result.fields
    assert good.grounding["word_ids"] == ["p1:w0"]
    assert good.review_outcome == "auto_accept"
    assert bad.grounding is None
    assert bad.validation_status == "failed"
    assert bad.review_outcome == "human_review"
    assert bad.score == 0.9


@pytest.mark.parametrize("source", ["p1:t0", "p1:l2", "p1:p2"])
def test_broad_reference_with_repeated_value_cannot_identify_one_occurrence(source):
    unit = page(["100", "100"])
    text = unit.content.strip()
    unit.lines.append(Line(id="p1:l2", text=text, word_ids=["p1:w0", "p1:w1"]))
    unit.paragraphs.append(Paragraph(id="p1:p2", text=text, span=Span(offset=0, length=len(text))))
    result, _ = extract(document(unit), [[pair("100", "p1:w0"), pair("100", source)]])
    assert len(result.fields) == 2


def test_conflicting_values_at_same_location_are_retained():
    result, _ = extract(document(page(["100"])), [[pair("100", "p1:w0"), pair("200", "p1:w0")]])
    assert [field.raw_value for field in result.fields] == ["100", "200"]


def test_same_value_in_distinct_sheet_cells_or_sheets_is_retained():
    units = [
        LayoutSheet(
            index=index,
            name=f"Sheet {index}",
            row_count=2,
            col_count=1,
            cells=[
                SheetCell(id=f"s{index}:A{row}", ref=f"A{row}", row=row, col=1, value="100")
                for row in (1, 2)
            ],
        )
        for index in (0, 1)
    ]
    responses = [
        [pair("100", f"s{index}:A{row}", index=index) for row in (1, 2)] for index in (0, 1)
    ]
    result, _ = extract(document(*units), responses, chunking={"strategy": "sheet"})
    assert len(result.fields) == 4
    assert [
        (field.grounding["unit_index"], field.grounding["cell_range"]) for field in result.fields
    ] == [(0, "A1"), (0, "A2"), (1, "A1"), (1, "A2")]


def test_selection_marks_preserve_distinct_marks_and_deduplicate_one_mark():
    unit = page([])
    unit.selection_marks = [
        SelectionMark(id=f"p1:sm{row}", state="selected", polygon=box(row)) for row in (0, 1)
    ]
    pairs = [pair("selected", f"p1:sm{row}", name="Approved") for row in (0, 1, 0)]
    result, _ = extract(document(unit), [pairs])
    assert len(result.fields) == 2
    assert [field.grounding["word_ids"] for field in result.fields] == [["p1:sm0"], ["p1:sm1"]]


def test_unverified_geometry_and_fuzzy_matches_remain_separate():
    unit = page(["Sample"])
    unit.words[0].polygon = []
    result, _ = extract(document(unit), [[pair("Sample", "p1:w0"), pair("Sample", "p1:w0")]])
    assert len(result.fields) == 2
    unit.words[0].polygon = box(0)
    result, _ = extract(document(unit), [[pair("Sampl", "p1:w0"), pair("Sampl", "p1:w0")]])
    assert len(result.fields) == 2
    assert all(field.grounding["method"] == "fuzzy" for field in result.fields)


@pytest.mark.parametrize("source", [None, "p1:missing"])
def test_unknown_unit_is_retained_with_failed_evidence_review(source):
    result, _ = extract(
        document(page(["100"])),
        [[pair("100", "p1:w0"), pair("100", source, index=99)]],
    )
    assert len(result.fields) == 2
    assert result.fields[1].grounding is None
    assert result.fields[1].validation_status == "failed"
    assert result.fields[1].review_outcome == "human_review"


def test_page_only_citations_remain_separate_even_with_matching_grounding():
    prediction = pair("100", None, sources=[{"unit_index": 0, "ids": []}])
    result, _ = extract(document(page(["100"])), [[prediction, prediction]])
    assert len(result.fields) == 2


def test_digit_match_canonicalizes_value_words_across_wider_line_citations():
    unit = page(["1,234"])
    unit.words.insert(
        0, Word(id="p1:w1", text="Total", polygon=box(0), span=Span(offset=0, length=5))
    )
    unit.lines[0].word_ids.insert(0, "p1:w1")
    result, _ = extract(document(unit), [[pair("1234", "p1:w0"), pair("1234", "p1:l0")]])
    assert len(result.fields) == 1


def test_actual_chunk_overlap_deduplicates_only_complete_submitted_occurrences():
    values = [f"V{row:03}" for row in range(100)]
    unit = page(values)
    # Keep rows separately visible so several complete rows survive each overlap.
    unit.tables = []
    doc = document(unit)
    config = {"strategy": "context_length", "chunk_chars": 2000, "overlap_chars": 600}
    layout_config = {"link_row_bands": False}
    cfg = ExtractStructuredConfig.model_validate(
        {"mode": "default", "chunking": config, "layout": layout_config}
    )
    plan = plan_chunks(preserve(doc, cfg.layout), cfg.chunking)
    responses = [
        [
            pair(value, f"p1:p{row}")
            for row, value in enumerate(values)
            if f"Date of Birth {value}  [p1:p{row}]" in chunk.text
        ]
        for chunk in plan.chunks
    ]
    assert len(plan.chunks) > 1
    assert sum(len(response) for response in responses) > len(values)
    result, _ = extract(doc, responses, chunking=config, layout=layout_config)
    assert [field.raw_value for field in result.fields] == values


def test_partial_chunk_citation_does_not_suppress_a_visible_occurrence(monkeypatch):
    from docai.layout.chunk import Chunk, ChunkPlan

    unit = page(["100", "200"])
    doc = document(unit)
    # Both cite a real page location, but the second chunk submitted only another row.
    chunks = [
        Chunk(0, "=== PAGE 1 (unit 0) ===\nDate of Birth 100  [p1:l0]", [0], "context_length"),
        Chunk(1, "=== PAGE 1 (unit 0) ===\nDate of Birth 200  [p1:l1]", [0], "context_length"),
    ]
    monkeypatch.setattr(
        "docai.workflows.extract_structured.plan_chunks",
        lambda *args, **kwargs: ChunkPlan(chunks, "context_length"),
    )
    result, _ = extract(doc, [[pair("100", "p1:l0")], [pair("100", "p1:l0")]])
    assert len(result.fields) == 2


def test_numeric_sheet_alias_deduplicates_matching_cell_occurrence():
    sheet = LayoutSheet(
        index=0,
        name="Amounts",
        row_count=1,
        col_count=1,
        cells=[SheetCell(id="s0:A1", ref="A1", row=1, col=1, value="1,000.00")],
    )
    result, _ = extract(document(sheet), [[pair("1000.00", "s0:A1"), pair("1000.00", "s0:A1")]])
    assert len(result.fields) == 1
    assert result.fields[0].grounding["cell_range"] == "A1"


def test_overlapping_phrase_matches_do_not_establish_unique_occurrence():
    unit = LayoutPage(
        index=0,
        number=1,
        content="A A A",
        words=[Word(id=f"p1:w{row}", text="A", polygon=box(row)) for row in range(3)],
        lines=[
            Line(
                id="p1:l0",
                text="A A A",
                polygon=box(0),
                word_ids=[f"p1:w{row}" for row in range(3)],
            )
        ],
    )
    narrow = pair("A A", "p1:w0", sources=[{"unit_index": 0, "ids": ["p1:w0", "p1:w1"]}])
    result, _ = extract(document(unit), [[narrow, pair("A A", "p1:l0")]])
    assert len(result.fields) == 2


def test_repeated_records_keep_unknown_confidence_and_normal_review():
    result, _ = extract(
        document(page(["100", "200"])),
        [[pair("100", "p1:w0", confidence=None), pair("200", "p1:w1", confidence=None)]],
        routing=[{"when": {"min_score": 0.5}, "outcome": "auto_accept"}],
    )
    assert len(result.fields) == 2
    assert all(
        field.score is None and field.review_outcome == "human_review" for field in result.fields
    )


def test_repair_provenance_and_review_survive_later_duplicate_without_trust_upgrade():
    candidates = [
        pair("100", "p1:l0"),
        pair("200", "p1:l0", confidence=0.7),
        pair("200", "p1:l1", confidence=1),
    ]
    repairs = [{"field_index": 1, "sources": [{"unit_index": 0, "ids": ["p1:l1"]}]}]
    result, calls = extract(
        document(page(["100", "200"])), [candidates], repairs=repairs, citation_repair=True
    )
    assert [call.stage for call in calls] == ["generic_kv", "citation_repair"]
    assert [field.raw_value for field in result.fields] == ["100", "200"]
    repaired = result.fields[1]
    assert repaired.score == 0.7
    assert repaired.grounding["word_ids"] == ["p1:w1"]
    assert repaired.grounding["citation_repaired"] is True
    assert repaired.validation_status == "warning"
    assert repaired.review_outcome == "human_review"
    assert any(
        "Source citations were corrected" in message for message in repaired.validation_messages
    )
