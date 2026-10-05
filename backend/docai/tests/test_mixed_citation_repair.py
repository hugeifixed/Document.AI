"""Invalid extra IDs may be repaired only within uniquely verified submitted evidence."""

import json
from types import SimpleNamespace
from typing import Literal

import pytest

from docai.adapters.llm.base import LLMCall
from docai.schemas.config import ExtractStructuredConfig
from docai.schemas.layout import (
    LayoutDocument,
    LayoutPage,
    LayoutSheet,
    Line,
    SelectionMark,
    SheetCell,
    Span,
    Table,
    TableCell,
    Word,
)
from docai.schemas.llm import FieldOut, StructuredResult
from docai.services.extraction_visualization import collect_labels
from docai.workflows.base import DocumentResult, PromptRef, WorkflowContext
from docai.workflows.citation_repair import CitationRepairer
from docai.workflows.extract_structured import ExtractStructured


def rectangle(row):
    y = 0.1 + row * 0.2
    return [0.4, y, 0.6, y, 0.6, y + 0.05, 0.4, y + 0.05]


def form_page(values=("01/02/80", "01/02/80"), *, index=0, table=True):
    prefix = f"p{index + 1}"
    content = ""
    words, lines, cells = [], [], []
    for row, value in enumerate(values):
        text = f"DOB {value}"
        start = len(content)
        words.extend(
            [
                Word(
                    id=f"{prefix}:w{row * 2}",
                    text="DOB",
                    span=Span(offset=start, length=3),
                    polygon=rectangle(row),
                ),
                Word(
                    id=f"{prefix}:w{row * 2 + 1}",
                    text=value,
                    span=Span(offset=start + 4, length=len(value)),
                    polygon=rectangle(row),
                ),
            ]
        )
        span = Span(offset=start, length=len(text))
        lines.append(Line(id=f"{prefix}:l{row}", text=text, span=span, polygon=rectangle(row)))
        cells.append(
            TableCell(
                id=f"{prefix}:t0:r{row * 2}:c0",
                row=row * 2,
                col=0,
                row_span=2,
                text=text,
                span=span,
            )
        )
        content += text + "\n"
    return LayoutPage(
        index=index,
        number=index + 1,
        content=content,
        words=words,
        lines=lines,
        tables=[Table(id=f"{prefix}:t0", row_count=len(values) * 2, col_count=1, cells=cells)]
        if table
        else [],
    )


def document(*units):
    return LayoutDocument(
        document_id="synthetic", source_format="pdf", service="fixture", units=units
    )


def ref(*ids, unit=0):
    return {"unit_index": unit, "ids": list(ids)}


def prediction(name, value, *ids):
    return {"name": name, "value": value, "confidence": 0.81, "sources": [ref(*ids)]}


def workflow_context(invoke, *, mode="default", enabled=True, specs=()):
    return WorkflowContext(
        workflow_type="extract_structured",
        config=ExtractStructuredConfig.model_validate(
            {
                "mode": mode,
                "schema": {"name": "synthetic", "fields": list(specs)},
                "citation_repair": enabled,
                "routing": [{"when": {"min_score": 0}, "outcome": "auto_accept"}],
            }
        ),
        llm=SimpleNamespace(key="fixture", invoke=invoke),
        prompts={
            stage: PromptRef(stage, 1, "", "{content}") for stage in ("generic_kv", "extraction")
        },
        layout_adapter_key="fixture",
    )


def extract(layout, candidates, patches, *, mode="default", enabled=True, specs=()):
    calls, discarded = [], []

    def invoke(call):
        calls.append(call)
        payload = (
            {"repairs": patches}
            if call.stage == "citation_repair"
            else {"pairs" if mode == "default" else "fields": candidates}
        )
        return StructuredResult(
            parsed=call.schema.model_validate(payload),
            raw_response="{}",
            model_deployment="fixture",
        )

    ctx = workflow_context(invoke, mode=mode, enabled=enabled, specs=specs)
    ctx.checkpoint_discard = lambda call: discarded.append(call.stage)
    result = ExtractStructured().process_document(ctx, layout)
    return result, calls, discarded


@pytest.mark.parametrize("mode", ["default", "custom"])
@pytest.mark.parametrize("kind,source", [("merged", "p1:t0:r0:c0"), ("line", "p1:l0")])
def test_mixed_scalar_repair_retains_both_dates_and_original_provenance(mode, kind, source):
    layout = document(form_page(table=kind == "merged"))
    second_source = "p1:t0:r2:c0" if kind == "merged" else "p1:l1"
    candidates = [
        prediction("DOB", "01/02/80", source, "p1:invented"),
        prediction("DOB" if mode == "default" else "other", "01/02/80", second_source),
    ]
    patches = [{"field_index": 0, "sources": [ref(source)]}]
    result, calls, _discarded = extract(
        layout, candidates, patches, mode=mode, specs=[{"name": "DOB"}, {"name": "other"}]
    )
    assert [call.stage for call in calls] == [
        "generic_kv" if mode == "default" else "extraction",
        "citation_repair",
    ]
    first, second = result.fields
    assert [f.raw_value for f in result.fields] == ["01/02/80", "01/02/80"]
    assert first.score == second.score == 0.81
    assert first.grounding["word_ids"] == ["p1:w1"]
    assert second.grounding["word_ids"] == ["p1:w3"]
    assert first.grounding["citation_repaired"] and first.review_outcome == "human_review"
    assert second.review_outcome == "auto_accept"
    assert result.raw_responses[-1]["updates"][0]["original_sources"][0]["ids"] == [
        source,
        "p1:invented",
    ]
    assert result.raw_responses[-1]["updates"][0]["repaired_sources"][0]["ids"] == [source]
    assert calls[-1].mock_context["targets"][0]["anchor_sources"][0]["ids"] == [source]
    assert "anchor_value_ids" not in calls[-1].user and "p1:w1" not in calls[-1].user
    assert [label["boxed"] for label in collect_labels(result, layout)] == [True, True]


def test_disabled_mixed_repair_leaves_invalid_field_unboxed():
    layout = document(form_page())
    candidates = [prediction("DOB", "01/02/80", "p1:t0:r0:c0", "p1:invented")]
    result, calls, _discarded = extract(
        layout, candidates, [{"field_index": 0, "sources": [ref("p1:t0:r0:c0")]}], enabled=False
    )
    assert len(calls) == 1
    assert result.fields[0].grounding is None
    assert result.fields[0].validation_status == "failed"
    assert result.fields[0].review_outcome == "human_review"


@pytest.mark.parametrize("mode", ["default", "custom"])
def test_patch_cannot_borrow_an_identical_date_from_another_record(mode):
    candidates = [prediction("DOB", "01/02/80", "p1:t0:r0:c0", "p1:invented")]
    result, calls, discarded = extract(
        document(form_page()),
        candidates,
        [{"field_index": 0, "sources": [ref("p1:t0:r2:c0")]}],
        mode=mode,
        specs=[{"name": "DOB"}],
    )
    assert len(calls) == 2
    assert result.fields[0].grounding is None
    assert result.fields[0].raw_value == "01/02/80" and result.fields[0].score == 0.81
    assert result.fields[0].review_outcome == "human_review"
    assert result.raw_responses[-1]["updates"] == []
    assert discarded == ["citation_repair"]


@pytest.mark.parametrize(
    "sources,unit_index",
    [
        ([ref("p1:invented")], None),
        ([ref("p1:t0", "p1:invented")], None),
        ([ref("p1:t0:r0:c0", "p2:w1")], None),
        ([ref("p1:t0:r0:c0", "p1:invented")], 1),
        ([ref("p1:t0:r0:c0"), ref("p3:invented", unit=2)], None),
    ],
    ids=["no-survivor", "ambiguous-table", "wrong-page-id", "mismatched-hint", "unsubmitted-page"],
)
def test_unsafe_mixed_citations_do_not_authorize_a_request(sources, unit_index):
    candidate = {"name": "DOB", "value": "01/02/80", "sources": sources, "unit_index": unit_index}
    result, calls, _discarded = extract(document(form_page(), form_page(index=1)), [candidate], [])
    assert len(calls) == 1
    assert result.fields[0].grounding is None and result.fields[0].review_outcome == "human_review"


def repair_submitted(layout, candidate, text, patches):
    calls, discarded = [], []

    def invoke(call):
        calls.append(call)
        return StructuredResult(
            parsed=call.schema.model_validate({"repairs": patches}),
            raw_response="{}",
            model_deployment="fixture",
        )

    ctx = workflow_context(invoke)
    ctx.checkpoint_discard = lambda call: discarded.append(call.stage)
    call = LLMCall(
        system="", user="", schema=StructuredResult, stage="generic_kv", mock_context={"text": text}
    )
    repairer = CitationRepairer(ctx, layout)
    result = DocumentResult()
    fields = repairer.repair(call, [candidate], {}, {0}, result)
    return fields, result, calls, discarded


def test_known_unsubmitted_ids_are_scope_violations_not_disposable_extras():
    original = FieldOut.model_validate(
        prediction("DOB", "01/02/80", "p1:l0", "p1:l1", "p1:invented")
    )
    fields, result, calls, _discarded = repair_submitted(
        document(form_page(values=("01/02/80", "03/04/82"), table=False)),
        original,
        "DOB 01/02/80 [p1:l0]",
        [{"field_index": 0, "sources": [ref("p1:l0")]}],
    )
    assert calls == [] and fields == [original] and result.raw_responses == []


@pytest.mark.parametrize("variant", ["label-only", "missing-geometry", "fuzzy"])
def test_surviving_reference_must_exactly_support_the_value_with_geometry(variant):
    page = form_page(table=False)
    value = "01/02/80"
    if variant == "label-only":
        page.lines[0].span = Span(offset=0, length=3)
        page.lines[0].text = "DOB"
    elif variant == "missing-geometry":
        page.words[1].polygon = []
    else:
        page.words[1].text = "Shipment"
        page.lines[0].text = page.content = "DOB Shipment"
        page.words[1].span = Span(offset=4, length=8)
        page.lines[0].span = Span(offset=0, length=12)
        value = "Shlpment"
    original = FieldOut.model_validate(prediction("field", value, "p1:l0", "p1:invented"))
    fields, _result, calls, _discarded = repair_submitted(
        document(page), original, f"{page.lines[0].text} [p1:l0]", []
    )
    assert not calls and fields == [original]


@pytest.mark.parametrize("borrow_neighbor", [False, True])
def test_mixed_list_property_repairs_preserve_records_and_nulls(borrow_neighbor):
    value = '[{"date":"01/02/80","absent":null},{"date":"01/02/80"}]'
    candidate = {
        "name": "people",
        "value": value,
        "confidence": 0.81,
        "property_sources": [
            {"path": "/0/date", "sources": [ref("p1:t0:r0:c0", "p1:invented")]},
            {"path": "/1/date", "sources": [ref("p1:t0:r2:c0")]},
        ],
    }
    patch = {
        "field_index": 0,
        "property_path": "/0/date",
        "sources": [ref("p1:t0:r2:c0" if borrow_neighbor else "p1:t0:r0:c0")],
    }
    result, calls, _discarded = extract(
        document(form_page()),
        [candidate],
        [patch],
        mode="custom",
        specs=[{"name": "people", "type": "list"}],
    )
    field = result.fields[0]
    assert len(calls) == 2 and field.raw_value == value and field.review_outcome == "human_review"
    first, second = field.property_evidence
    assert second["grounding"]["word_ids"] == ["p1:w3"]
    if borrow_neighbor:
        assert first["status"] == "invalid_reference" and first["grounding"] is None
        assert first["sources"][0]["ids"] == ["p1:t0:r0:c0", "p1:invented"]
    else:
        assert first["status"] == "grounded" and first["grounding"]["word_ids"] == ["p1:w1"]
        assert first["citation_repaired"]


def test_two_repeated_list_records_cannot_share_a_repaired_occurrence():
    candidate = {
        "name": "people",
        "value": '[{"date":"01/02/80"},{"date":"01/02/80"}]',
        "property_sources": [
            {"path": f"/{i}/date", "sources": [ref("p1:t0:r0:c0", f"p1:invented{i}")]}
            for i in (0, 1)
        ],
    }
    patches = [
        {"field_index": 0, "property_path": f"/{i}/date", "sources": [ref("p1:t0:r0:c0")]}
        for i in (0, 1)
    ]
    result, calls, discarded = extract(
        document(form_page()),
        [candidate],
        patches,
        mode="custom",
        specs=[{"name": "people", "type": "list"}],
    )
    assert len(calls) == 2 and discarded == ["citation_repair"]
    assert all(
        p["status"] == "invalid_reference" and p["grounding"] is None
        for p in result.fields[0].property_evidence
    )
    assert result.raw_responses[-1]["updates"] == []


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("borrow_neighbor", [False, True])
def test_mixed_checkbox_property_keeps_boolean_value_and_mark_identity(value, borrow_neighbor):
    state: Literal["selected", "unselected"] = "selected" if value else "unselected"
    page = LayoutPage(
        index=0,
        number=1,
        selection_marks=[
            SelectionMark(id=f"p1:sm{i}", state=state, polygon=rectangle(i)) for i in (0, 1)
        ],
    )
    raw = json.dumps([{"approved": value, "absent": None}])
    candidate = {
        "name": "approvals",
        "value": raw,
        "property_sources": [{"path": "/0/approved", "sources": [ref("p1:sm0", "p1:sm99")]}],
    }
    patch = {
        "field_index": 0,
        "property_path": "/0/approved",
        "sources": [ref("p1:sm1" if borrow_neighbor else "p1:sm0")],
    }
    result, calls, _discarded = extract(
        document(page),
        [candidate],
        [patch],
        mode="custom",
        specs=[{"name": "approvals", "type": "list"}],
    )
    field = result.fields[0]
    assert len(calls) == 2 and field.raw_value == raw
    assert json.loads(field.raw_value)[0] == {"approved": value, "absent": None}
    prop = field.property_evidence[0]
    assert prop["value"] is value
    if borrow_neighbor:
        assert prop["status"] == "invalid_reference" and prop["grounding"] is None
    else:
        assert prop["grounding"]["word_ids"] == ["p1:sm0"]
        assert prop["grounding"]["method"] == "selection_mark" and prop["citation_repaired"]


@pytest.mark.parametrize("cell", ["A1", "A2"])
def test_mixed_spreadsheet_reference_cannot_move_to_an_equal_neighbor(cell):
    sheet = LayoutSheet(
        index=0,
        name="Sheet",
        row_count=2,
        col_count=1,
        cells=[SheetCell(id=f"s0:A{i}", ref=f"A{i}", row=i, col=1, value="100") for i in (1, 2)],
    )
    result, calls, _discarded = extract(
        document(sheet),
        [prediction("total", "100", "s0:A1", "s0:A99")],
        [{"field_index": 0, "sources": [ref(f"s0:{cell}")]}],
    )
    assert len(calls) == 2 and result.fields[0].raw_value == "100"
    if cell == "A1":
        assert result.fields[0].grounding["cell_range"] == "A1"
        assert result.fields[0].grounding["citation_repaired"]
    else:
        assert result.fields[0].grounding is None and result.raw_responses[-1]["updates"] == []


def test_overlapping_phrase_is_not_a_unique_anchor():
    page = LayoutPage(
        index=0,
        number=1,
        content="A A A",
        words=[
            Word(id=f"p1:w{i}", text="A", span=Span(offset=i * 2, length=1), polygon=rectangle(i))
            for i in range(3)
        ],
        lines=[Line(id="p1:l0", text="A A A", span=Span(offset=0, length=5))],
    )
    original = FieldOut.model_validate(prediction("phrase", "A A", "p1:l0", "p1:invented"))
    fields, _result, calls, _discarded = repair_submitted(
        document(page), original, "A A A [p1:l0]", []
    )
    assert not calls and fields == [original]


def test_digit_matching_anchors_value_words_independently_of_label_width():
    page = LayoutPage(
        index=0,
        number=1,
        content="Code 12 34",
        words=[
            Word(id="p1:w0", text="Code", span=Span(offset=0, length=4), polygon=rectangle(0)),
            Word(id="p1:w1", text="12", span=Span(offset=5, length=2), polygon=rectangle(0)),
            Word(id="p1:w2", text="34", span=Span(offset=8, length=2), polygon=rectangle(0)),
        ],
        lines=[Line(id="p1:l0", text="Code 12 34", span=Span(offset=0, length=10))],
    )
    original = FieldOut.model_validate(prediction("code", "1234", "p1:l0", "p1:invented"))
    fields, result, calls, _discarded = repair_submitted(
        document(page),
        original,
        "Code 12 34 [p1:l0]\n12 [p1:w1]\n34 [p1:w2]",
        [{"field_index": 0, "sources": [ref("p1:w1", "p1:w2")]}],
    )
    assert len(calls) == 1
    assert fields[0].value == "1234" and fields[0].sources[0].ids == ["p1:w1", "p1:w2"]
    assert result.raw_responses[-1]["updates"][0]["original_sources"][0]["ids"] == [
        "p1:l0",
        "p1:invented",
    ]
