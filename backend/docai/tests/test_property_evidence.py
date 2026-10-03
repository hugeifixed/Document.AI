"""Property citations preserve row identity; citation repairs never change values."""

import json
from types import SimpleNamespace

import pytest

from docai.schemas.config import ExtractStructuredConfig
from docai.schemas.layout import LayoutDocument, LayoutPage, Line, SelectionMark, Span, Word
from docai.schemas.llm import FieldOut, SourceRef, StructuredResult
from docai.workflows.base import PromptRef, WorkflowContext
from docai.workflows.extract_structured import ExtractStructured


def fixture_layout():
    pages = []
    for index, value in enumerate(["100", "100"]):
        prefix = f"p{index + 1}"
        pages.append(
            LayoutPage(
                index=index,
                number=index + 1,
                content=f"Total\n{value}",
                words=[
                    Word(
                        id=f"{prefix}:w0",
                        text="Total",
                        span=Span(offset=0, length=5),
                        polygon=[0.1, 0.1, 0.2, 0.1, 0.2, 0.2, 0.1, 0.2],
                    ),
                    Word(
                        id=f"{prefix}:w1",
                        text=value,
                        span=Span(offset=6, length=3),
                        polygon=[0.3, 0.1, 0.4, 0.1, 0.4, 0.2, 0.3, 0.2],
                    ),
                ],
                lines=[
                    Line(
                        id=f"{prefix}:l0",
                        text="Total",
                        span=Span(offset=0, length=5),
                        polygon=[0.1, 0.1, 0.2, 0.1, 0.2, 0.2, 0.1, 0.2],
                    ),
                    Line(
                        id=f"{prefix}:l1",
                        text=value,
                        span=Span(offset=6, length=3),
                        polygon=[0.3, 0.3, 0.4, 0.3, 0.4, 0.4, 0.3, 0.4],
                    ),
                ],
            )
        )
    return LayoutDocument(
        document_id="invoices", source_format="pdf", service="fixture", units=pages
    )


def context(invoke, specs, *, mode="custom", citation_repair=None):
    config = {"mode": mode, "schema": {"name": "invoices", "fields": specs}}
    if citation_repair is not None:
        config["citation_repair"] = citation_repair
    return WorkflowContext(
        workflow_type="extract_structured",
        config=ExtractStructuredConfig.model_validate(config),
        llm=SimpleNamespace(key="fixture", invoke=invoke),
        prompts={
            stage: PromptRef(stage, 1, "", "{content}") for stage in ["extraction", "generic_kv"]
        },
        layout_adapter_key="fixture",
    )


def response(call, fields):
    return StructuredResult(
        parsed=call.schema.model_validate({"fields": fields}),
        raw_response="{}",
        model_deployment="fixture",
    )


def test_each_list_property_has_its_own_original_page_box_and_preserves_duplicates():
    value = json.dumps([{"amount": "100"}, {"amount": "100"}])

    def invoke(call):
        return response(
            call,
            [
                {
                    "name": "items",
                    "value": value,
                    "property_sources": [
                        {"path": "/0/amount", "sources": [{"unit_index": 0, "ids": ["p1:l1"]}]},
                        {"path": "/1/amount", "sources": [{"unit_index": 1, "ids": ["p2:l1"]}]},
                    ],
                }
            ],
        )

    field = (
        ExtractStructured()
        .process_document(context(invoke, [{"name": "items", "type": "list"}]), fixture_layout())
        .fields[0]
    )
    assert field.raw_value == value and field.grounding is None
    assert field.review_outcome == "human_review"
    assert [(p["path"], p["grounding"]["unit_index"]) for p in field.property_evidence] == [
        ("/0/amount", 0),
        ("/1/amount", 1),
    ]
    assert [p["grounding"]["word_ids"] for p in field.property_evidence] == [["p1:w1"], ["p2:w1"]]


@pytest.mark.parametrize("mode", ["custom", "default"])
def test_one_retry_corrects_only_the_citation_and_keeps_value(mode):
    calls = []

    def invoke(call):
        calls.append(call)
        if call.stage == "citation_repair":
            assert call.parameters["max_retries"] == 0
            return StructuredResult(
                parsed=call.schema.model_validate(
                    {
                        "repairs": [
                            {"field_index": 0, "sources": [{"unit_index": 0, "ids": ["p1:l1"]}]}
                        ]
                    }
                ),
                raw_response="{}",
                model_deployment="fixture",
            )
        return StructuredResult(
            parsed=call.schema.model_validate(
                {
                    "fields" if mode == "custom" else "pairs": [
                        {
                            "name": "total",
                            "value": "100",
                            "confidence": 0.8,
                            "unit_index": 0,
                            "sources": [{"unit_index": 0, "ids": ["p1:l0"]}],
                        }
                    ]
                }
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    result = ExtractStructured().process_document(
        context(invoke, [{"name": "total"}], mode=mode, citation_repair=True), fixture_layout()
    )
    field = result.fields[0]
    assert len(calls) == 2 and field.raw_value == "100" and field.score == 0.8
    assert field.grounding is not None and field.grounding["word_ids"] == ["p1:w1"]
    assert field.grounding["method"] == "exact" and field.grounding["citation_repaired"]
    assert result.raw_responses[-1]["stage"] == "citation_repair"


@pytest.mark.parametrize("mode", ["custom", "default"])
@pytest.mark.parametrize("citation_repair", [None, False])
def test_disabled_repair_keeps_unverified_values_for_review_and_verifies_valid_neighbors(
    mode, citation_repair
):
    calls = []
    candidates = [
        {
            "name": name,
            "value": "100",
            "confidence": 0.8,
            "unit_index": 0,
            "sources": [{"unit_index": 0, "ids": [source]}],
        }
        for name, source in [("unverified", "p1:l0"), ("verified", "p1:l1")]
    ]
    if mode == "custom":
        candidates.append(
            {
                "name": "items",
                "value": '[{"amount":"100"},{"amount":"100"}]',
                "property_sources": [
                    {"path": "/0/amount", "sources": [{"unit_index": 0, "ids": ["p1:l0"]}]},
                    {"path": "/1/amount", "sources": [{"unit_index": 1, "ids": ["p2:l1"]}]},
                ],
            }
        )

    def invoke(call):
        calls.append(call.stage)
        assert call.stage != "citation_repair", "Repair requires explicit opt-in"
        return StructuredResult(
            parsed=call.schema.model_validate(
                {"fields" if mode == "custom" else "pairs": candidates}
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    ctx = context(
        invoke,
        [{"name": "unverified"}, {"name": "verified"}, {"name": "items", "type": "list"}],
        mode=mode,
        citation_repair=citation_repair,
    )
    result = ExtractStructured().process_document(ctx, fixture_layout())
    assert ctx.config.citation_repair is False
    assert calls == ["extraction" if mode == "custom" else "generic_kv"]
    unverified, verified = result.fields[:2]
    assert unverified.raw_value == "100" and unverified.score == 0.8
    assert unverified.grounding is None and unverified.review_outcome == "human_review"
    assert verified.grounding is not None and verified.grounding["word_ids"] == ["p1:w1"]
    assert not any(r["stage"] == "citation_repair" for r in result.raw_responses)
    if mode == "custom":
        collection = result.fields[2]
        assert collection.review_outcome == "human_review"
        assert collection.property_evidence[0]["status"] == "value_not_found"
        assert collection.property_evidence[0]["sources"][0]["ids"] == ["p1:l0"]
        assert collection.property_evidence[1]["grounding"]["word_ids"] == ["p2:w1"]


def test_property_sources_survive_field_model_roundtrip():
    data = {
        "name": "items",
        "value": '["100"]',
        "property_sources": [{"path": "/0", "sources": [{"unit_index": 0, "ids": ["p1:l1"]}]}],
    }
    parsed = FieldOut.model_validate(data)
    assert parsed.model_dump()["property_sources"][0]["path"] == "/0"
    assert parsed.property_sources[0].sources[0].ids == ["p1:l1"]
    assert FieldOut.model_validate_json(parsed.model_dump_json()) == parsed


def _properties(doc, value, refs, allowed=None):
    from docai.grounding.properties import ground_properties

    candidate = FieldOut.model_validate(
        {"name": "items", "value": json.dumps(value), "property_sources": refs}
    )
    return ground_properties(
        doc, candidate, allowed if allowed is not None else {p.index for p in doc.pages}
    )


@pytest.mark.parametrize(
    "refs,status",
    [
        ([], "missing_reference"),
        ([{"unit_index": 0, "ids": []}], "missing_reference"),
        ([{"unit_index": 0, "ids": ["p1:invented"]}], "invalid_reference"),
        ([{"unit_index": 0, "ids": ["p2:l1"]}], "invalid_reference"),
        ([{"unit_index": 0, "ids": ["p1:l0"]}], "value_not_found"),
    ],
)
def test_missing_or_invalid_property_citation_does_not_search_elsewhere(refs, status):
    result = _properties(
        fixture_layout(), [{"amount": "100"}], [{"path": "/0/amount", "sources": refs}]
    )
    assert result[0]["status"] == status and result[0]["grounding"] is None


def test_one_invalid_property_does_not_hide_its_valid_neighbor():
    props = _properties(
        fixture_layout(),
        [{"amount": "100", "other": "100"}],
        [
            {"path": "/0/amount", "sources": [{"unit_index": 0, "ids": ["p1:invented"]}]},
            {"path": "/0/other", "sources": [{"unit_index": 0, "ids": ["p1:l1"]}]},
        ],
    )
    assert props[0]["status"] == "invalid_reference"
    assert props[1]["status"] == "grounded" and props[1]["grounding"]["word_ids"] == ["p1:w1"]


def test_repeated_rows_cannot_reuse_one_physical_value_occurrence():
    props = _properties(
        fixture_layout(),
        [{"amount": "100"}, {"amount": "100"}],
        [
            {"path": f"/{i}/amount", "sources": [{"unit_index": 0, "ids": ["p1:l1"]}]}
            for i in range(2)
        ],
    )
    assert [p["status"] for p in props] == ["ambiguous_row", "ambiguous_row"]
    assert all(p["grounding"] is None for p in props)


def test_nested_repeated_records_cannot_reuse_one_occurrence():
    props = _properties(
        fixture_layout(),
        [{"payments": [{"amount": "100"}, {"amount": "100"}]}],
        [
            {
                "path": f"/0/payments/{i}/amount",
                "sources": [{"unit_index": 0, "ids": ["p1:l1"]}],
            }
            for i in range(2)
        ],
    )
    assert all(p["status"] == "ambiguous_row" and not p["grounding"] for p in props)


def test_numeric_object_keys_are_not_treated_as_repeated_array_indexes():
    props = _properties(
        fixture_layout(),
        [{"0": {"amount": "100"}, "1": {"amount": "100"}}],
        [
            {"path": f"/0/{i}/amount", "sources": [{"unit_index": 0, "ids": ["p1:l1"]}]}
            for i in range(2)
        ],
    )
    assert all(p["status"] == "grounded" for p in props)


def test_broad_reference_with_duplicate_values_on_one_page_is_ambiguous():
    doc = fixture_layout()
    doc.pages[0].words.append(doc.pages[0].words[1].model_copy(update={"id": "p1:w2"}))
    props = _properties(
        doc,
        ["100"],
        [{"path": "/0", "sources": [{"unit_index": 0, "ids": ["p1:w1", "p1:w2"]}]}],
    )
    assert props[0]["status"] == "ambiguous_reference" and props[0]["grounding"] is None


def test_broad_references_with_repeated_values_are_ambiguous():
    props = _properties(
        fixture_layout(),
        ["100"],
        [{"path": "/0", "sources": [{"unit_index": i, "ids": [f"p{i + 1}:l1"]} for i in range(2)]}],
    )
    assert props[0]["status"] == "ambiguous_reference"


def test_duplicate_pointer_and_unknown_pointer_do_not_produce_boxes():
    ref = {"path": "/0/amount", "sources": [{"unit_index": 0, "ids": ["p1:l1"]}]}
    props = _properties(
        fixture_layout(), [{"amount": "100"}], [ref, ref, {**ref, "path": "/01/amount"}]
    )
    assert [p["status"] for p in props] == ["duplicate_path", "invalid_path"]


def test_nested_pointer_escapes_and_false_zero_values_survive():
    doc = fixture_layout()
    doc.pages[0].words = [
        Word(id="p1:w0", text="false", polygon=[0.1, 0.1, 0.2, 0.1, 0.2, 0.2, 0.1, 0.2]),
        Word(id="p1:w1", text="0", polygon=[0.3, 0.1, 0.4, 0.1, 0.4, 0.2, 0.3, 0.2]),
    ]
    props = _properties(
        doc,
        [{"a/b~c": {"flag": False, "zero": 0, "absent": None, "empty": ""}}],
        [
            {"path": "/0/a~1b~0c/flag", "sources": [{"unit_index": 0, "ids": ["p1:w0"]}]},
            {"path": "/0/a~1b~0c/zero", "sources": [{"unit_index": 0, "ids": ["p1:w1"]}]},
        ],
    )
    assert [p["value"] for p in props] == [False, 0]
    assert all(p["status"] == "grounded" for p in props)


def test_boolean_property_requires_the_cited_checkbox_state():
    doc = fixture_layout()
    doc.pages[0].selection_marks = [
        SelectionMark(
            id="p1:sm0", state="unselected", polygon=[0.1, 0.1, 0.2, 0.1, 0.2, 0.2, 0.1, 0.2]
        )
    ]
    ref = {"path": "/0/flag", "sources": [{"unit_index": 0, "ids": ["p1:sm0"]}]}
    false = _properties(doc, [{"flag": False, "absent": None}], [ref])[0]
    true = _properties(doc, [{"flag": True}], [ref])[0]
    assert false["value"] is False and false["grounding"]["method"] == "selection_mark"
    assert true["status"] == "unverified_checkbox" and true["grounding"] is None


@pytest.mark.parametrize("excluded", [False, True])
def test_properties_cannot_cross_a_chunk_or_skipped_page(excluded):
    doc = fixture_layout()
    doc.pages[1].excluded_from_analysis = excluded
    props = _properties(
        doc,
        ["100"],
        [{"path": "/0", "sources": [{"unit_index": 1, "ids": ["p2:l1"]}]}],
        allowed={0, 1} if excluded else {0},
    )
    assert props[0]["status"] == "invalid_reference"


def test_missing_geometry_and_fuzzy_only_matches_remain_unverified():
    doc = fixture_layout()
    doc.pages[0].words[1].polygon = []
    ref = {"path": "/0", "sources": [{"unit_index": 0, "ids": ["p1:l1"]}]}
    assert _properties(doc, ["100"], [ref])[0]["status"] == "missing_geometry"
    doc.pages[0].words[1].text = "Shipment"
    assert _properties(doc, ["Shlpment"], [ref])[0]["status"] == "value_not_found"


@pytest.mark.parametrize(
    "patches",
    [
        [{"field_index": 0, "sources": [{"unit_index": 0, "ids": ["p1:invented"]}]}],
        [{"field_index": 0, "sources": [{"unit_index": 1, "ids": ["p2:l1"]}]}],
        [{"field_index": 0, "sources": []}],
        [{"field_index": 7, "sources": [{"unit_index": 0, "ids": ["p1:l1"]}]}],
        [{"field_index": 0, "sources": [{"unit_index": 0, "ids": ["p1:l1"]}]}] * 2,
    ],
)
def test_invalid_correction_keeps_original_value_and_does_not_retry_again(patches):
    calls = []

    def invoke(call):
        calls.append(call.stage)
        if call.stage == "citation_repair":
            return StructuredResult(
                parsed=call.schema.model_validate({"repairs": patches}),
                raw_response="{}",
                model_deployment="fixture",
            )
        return response(
            call,
            [{"name": "total", "value": "100", "sources": [{"unit_index": 0, "ids": ["p1:l0"]}]}],
        )

    result = ExtractStructured().process_document(
        context(invoke, [{"name": "total"}], citation_repair=True), fixture_layout()
    )
    assert calls == ["extraction", "citation_repair"]
    assert result.fields[0].raw_value == "100" and result.fields[0].grounding is None
    assert result.fields[0].review_outcome == "human_review"


@pytest.mark.parametrize("error", ["provider", "schema"])
def test_optional_correction_failure_retains_original_and_sanitizes_logs(error, capsys):
    from docai.exceptions import IntegrationError, InvalidModelOutput

    def invoke(call):
        if call.stage == "citation_repair":
            if error == "provider":
                raise IntegrationError("private provider payload")
            raise InvalidModelOutput("private provider payload")
        return response(
            call,
            [{"name": "total", "value": "100", "sources": [{"unit_index": 0, "ids": ["p1:l0"]}]}],
        )

    result = ExtractStructured().process_document(
        context(invoke, [{"name": "total"}], citation_repair=True), fixture_layout()
    )
    assert result.fields[0].raw_value == "100" and result.fields[0].grounding is None
    assert "private provider payload" not in str(result.warnings) + capsys.readouterr().err


def test_correction_budget_is_one_per_invocation_across_multiple_chunks():
    stages = []

    def invoke(call):
        stages.append(call.stage)
        if call.stage == "citation_repair":
            return StructuredResult(
                parsed=call.schema.model_validate({"repairs": []}),
                raw_response="{}",
                model_deployment="fixture",
            )
        index = call.chunk_index
        return response(
            call,
            [
                {
                    "name": "total",
                    "value": "100",
                    "sources": [{"unit_index": index, "ids": [f"p{index + 1}:l0"]}],
                }
            ],
        )

    ctx = context(invoke, [{"name": "total"}], citation_repair=True)
    ctx.config.chunking.strategy = "page"
    result = ExtractStructured().process_document(ctx, fixture_layout())
    assert stages == ["extraction", "citation_repair", "extraction"]
    assert result.extraction_chunks == 2


def test_correction_preserves_governed_instructions_and_field_guidance():
    calls = []

    def invoke(call):
        calls.append(call)
        if call.stage == "citation_repair":
            assert "Follow governed instructions" in call.system
            assert '"guidance": "Use the invoice total"' in call.user
            return StructuredResult(
                parsed=call.schema.model_validate({"repairs": []}),
                raw_response="{}",
                model_deployment="fixture",
            )
        return response(
            call,
            [{"name": "total", "value": "100", "sources": [{"unit_index": 0, "ids": ["p1:l0"]}]}],
        )

    ctx = context(
        invoke, [{"name": "total", "guidance": "Use the invoice total"}], citation_repair=True
    )
    ctx.prompts["extraction"] = PromptRef(
        "extraction", 1, "Follow governed instructions", "{content}"
    )
    ExtractStructured().process_document(ctx, fixture_layout())
    assert len(calls) == 2


def test_oversized_correction_does_not_call_provider():
    from docai.adapters.llm.base import LLMCall
    from docai.workflows.base import DocumentResult
    from docai.workflows.citation_repair import CitationRepairer

    def invoke(call):
        pytest.fail("An oversized correction must not call the provider")

    ctx = context(invoke, [{"name": "total"}], citation_repair=True)
    ctx.config.chunking.max_request_chars = 1000
    candidate = FieldOut.model_validate(
        {"name": "total", "value": "100", "sources": [{"unit_index": 0, "ids": ["p1:l0"]}]}
    )
    call = LLMCall(
        stage="extraction",
        system="",
        user="",
        schema=StructuredResult,
        mock_context={"text": "Total [p1:l0]\n100 [p1:l1]\n" + "X" * 1000},
    )
    result = DocumentResult()
    repairer = CitationRepairer(ctx, fixture_layout())
    assert repairer.repair(call, [candidate], {"total": "string"}, {0}, result) == [candidate]
    assert not repairer.attempted and "input limit" in result.warnings[0]


def test_one_request_repairs_scalar_and_property_citations_without_changing_values():
    calls = []
    value = '[{"amount": "100"}, {"amount": "100", "absent": null}]'

    def invoke(call):
        calls.append(call)
        if call.stage == "citation_repair":
            assert '"property_path": "/0/amount"' in call.user
            assert '"record_context": {"amount": "100"}' in call.user
            assert '"id": "p1:l1", "text": "100"' in call.user
            return StructuredResult(
                parsed=call.schema.model_validate(
                    {
                        "repairs": [
                            {"field_index": 0, "sources": [{"unit_index": 0, "ids": ["p1:l1"]}]},
                            {
                                "field_index": 1,
                                "property_path": "/0/amount",
                                "sources": [{"unit_index": 0, "ids": ["p1:l1"]}],
                            },
                        ]
                    }
                ),
                raw_response="{}",
                model_deployment="fixture",
            )
        return response(
            call,
            [
                {
                    "name": "total",
                    "value": "100",
                    "confidence": 0.8,
                    "sources": [{"unit_index": 0, "ids": ["p1:l0"]}],
                },
                {
                    "name": "items",
                    "value": value,
                    "confidence": 0.7,
                    "property_sources": [
                        {"path": "/0/amount", "sources": [{"unit_index": 0, "ids": ["p1:l0"]}]},
                        {"path": "/1/amount", "sources": [{"unit_index": 1, "ids": ["p2:l1"]}]},
                    ],
                },
            ],
        )

    doc = fixture_layout()
    for page in doc.pages:
        for line, word in zip(page.lines, page.words, strict=True):
            line.polygon = list(word.polygon)
    result = ExtractStructured().process_document(
        context(
            invoke, [{"name": "total"}, {"name": "items", "type": "list"}], citation_repair=True
        ),
        doc,
    )
    scalar, collection = result.fields
    assert [c.stage for c in calls] == ["extraction", "citation_repair"]
    assert scalar.raw_value == "100" and scalar.score == 0.8
    assert collection.raw_value == value and collection.score == 0.7
    assert all(p["status"] == "grounded" for p in collection.property_evidence)
    assert collection.property_evidence[0]["citation_repaired"]
    assert "citation_repaired" not in collection.property_evidence[1]
    assert collection.review_outcome == "human_review" and collection.grounding is None


@pytest.mark.parametrize(
    "path,refs",
    [
        (None, [{"unit_index": 0, "ids": ["p1:l1"]}]),
        ("/01/amount", [{"unit_index": 0, "ids": ["p1:l1"]}]),
        ("/0/amount", [{"unit_index": 1, "ids": ["p2:l1"]}]),
        ("/0/amount", [{"unit_index": 0, "ids": ["p1:invented"]}]),
        ("/0/amount", []),
    ],
)
def test_invalid_property_repair_retains_original_and_revokes_checkpoint(path, refs):
    discarded = []

    def invoke(call):
        if call.stage == "citation_repair":
            return StructuredResult(
                parsed=call.schema.model_validate(
                    {"repairs": [{"field_index": 0, "property_path": path, "sources": refs}]}
                ),
                raw_response="{}",
                model_deployment="fixture",
            )
        return response(
            call,
            [
                {
                    "name": "items",
                    "value": '[{"amount":"100"}]',
                    "property_sources": [
                        {"path": "/0/amount", "sources": [{"unit_index": 0, "ids": ["p1:l0"]}]},
                    ],
                }
            ],
        )

    ctx = context(invoke, [{"name": "items", "type": "list"}], citation_repair=True)
    ctx.checkpoint_discard = lambda call: discarded.append(call.stage)
    field = ExtractStructured().process_document(ctx, fixture_layout()).fields[0]
    assert field.raw_value == '[{"amount":"100"}]'
    assert field.property_evidence[0]["status"] == "value_not_found"
    assert field.property_evidence[0]["sources"][0]["ids"] == ["p1:l0"]
    assert "citation_repaired" not in field.property_evidence[0]
    assert discarded == ["citation_repair"]


@pytest.mark.parametrize("first_already_verified", [False, True])
def test_property_repair_cannot_reuse_an_occurrence_from_another_record(first_already_verified):
    def invoke(call):
        if call.stage == "citation_repair":
            return StructuredResult(
                parsed=call.schema.model_validate(
                    {
                        "repairs": [
                            {
                                "field_index": 0,
                                "property_path": f"/{i}/amount",
                                "sources": [{"unit_index": 0, "ids": ["p1:l1"]}],
                            }
                            for i in range(2)
                        ]
                    }
                ),
                raw_response="{}",
                model_deployment="fixture",
            )
        return response(
            call,
            [
                {
                    "name": "items",
                    "value": '[{"amount":"100"},{"amount":"100"}]',
                    "property_sources": [
                        {
                            "path": f"/{i}/amount",
                            "sources": [
                                {
                                    "unit_index": 0,
                                    "ids": [
                                        "p1:l1" if i == 0 and first_already_verified else "p1:l0"
                                    ],
                                }
                            ],
                        }
                        for i in range(2)
                    ],
                }
            ],
        )

    field = (
        ExtractStructured()
        .process_document(
            context(invoke, [{"name": "items", "type": "list"}], citation_repair=True),
            fixture_layout(),
        )
        .fields[0]
    )
    assert field.property_evidence[1]["grounding"] is None
    assert bool(field.property_evidence[0]["grounding"]) == first_already_verified
    assert all(not p.get("citation_repaired") for p in field.property_evidence)


@pytest.mark.django_db
@pytest.mark.parametrize("enabled", [False, True])
def test_run_snapshot_preserves_the_citation_repair_setting(project, dataset, admin, enabled):
    from docai.services import governance, runs

    workflow = governance.create_workflow_version(
        project,
        "repair-policy",
        "extract_structured",
        {
            "schema": {"name": "invoices", "fields": [{"name": "total"}]},
            "citation_repair": enabled,
        },
        admin,
    )
    run = runs.create_run(project, workflow, dataset, admin)
    assert run.config_snapshot["config"]["citation_repair"] is enabled
    workflow.config["citation_repair"] = not enabled
    assert runs.build_context(run).config.citation_repair is enabled


@pytest.mark.django_db
@pytest.mark.parametrize("corrected", [False, True])
@pytest.mark.parametrize("action", ["accept", "correct", "mark_absent"])
def test_property_boxes_persist_as_spans_on_the_collection(
    project, dataset, admin, sample_workflow, w2_pdf, corrected, action
):
    from dataclasses import asdict

    from docai.models import SourceUnit
    from docai.services import export, ingestion, labeling, review, runs

    doc = ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    SourceUnit.objects.create(document=doc, kind="page", index=0)
    SourceUnit.objects.create(document=doc, kind="page", index=1)
    run = runs.create_run(project, sample_workflow, dataset, admin)

    def invoke(call):
        if call.stage == "citation_repair":
            return StructuredResult(
                parsed=call.schema.model_validate(
                    {
                        "repairs": [
                            {
                                "field_index": 0,
                                "property_path": "/0",
                                "sources": [{"unit_index": 0, "ids": ["p1:l1"]}],
                            }
                        ]
                    }
                ),
                raw_response="{}",
                model_deployment="fixture",
            )
        return response(
            call,
            [
                {
                    "name": "items",
                    "value": '["100","100"]',
                    "property_sources": [
                        {
                            "path": "/0",
                            "sources": [
                                {"unit_index": 0, "ids": ["p1:l0" if corrected else "p1:l1"]}
                            ],
                        },
                        {"path": "/1", "sources": [{"unit_index": 1, "ids": ["p2:l1"]}]},
                    ],
                }
            ],
        )

    result = ExtractStructured().process_document(
        context(invoke, [{"name": "items", "type": "list"}], citation_repair=corrected),
        fixture_layout(),
    )
    runs.persist_result(run, doc, result, fixture_layout())
    field = run.fields.get()
    assert field.spans.count() == 2
    span = field.spans.get(unit__index=0)
    assert not field.grounded and field.review_status == "needs_review"
    assert span.word_ids == ["p1:w1"] and span.mapping_method == "exact"
    assert span.exceptions == ["list_property_path=/0"] + (["citation_repair"] if corrected else [])
    assert span.text == "100"
    assert asdict(result)["fields"][0]["property_evidence"][0]["path"] == "/0"
    exported = export.run_package(run)["fields"][0]
    assert exported["source"]["property_spans"][0]["path"] == "/0"
    assert exported["source"]["property_spans"][0]["word_ids"] == ["p1:w1"]
    assert exported["source"]["property_spans"][0]["citation_repaired"] == corrected
    assert exported["source"]["property_spans"][1]["unit_index"] == 1

    review.act_on_field(field, action, admin, value='["200"]' if action == "correct" else None)
    label = labeling.promote_field_to_ground_truth(field, admin)
    assert label.expected_value == field.reviewed_value
    assert label.unit is None and label.azure_span == {} and not label.spans.exists()
    assert field.spans.count() == 2  # Individual property evidence remains available.
    assert export.run_package(run)["ground_truth"][0]["unit_index"] is None


@pytest.mark.parametrize("patch_id", ["p1:l2", "p1:w2"])
def test_repair_cannot_borrow_an_unseen_same_page_occurrence(patch_id):
    from docai.adapters.llm.base import LLMCall
    from docai.workflows.base import DocumentResult
    from docai.workflows.citation_repair import CitationRepairer

    layout = fixture_layout()
    page = layout.pages[0]
    page.content += "\n100"
    page.words.append(
        page.words[1].model_copy(update={"id": "p1:w2", "span": Span(offset=10, length=3)})
    )
    page.lines.append(
        page.lines[1].model_copy(update={"id": "p1:l2", "span": Span(offset=10, length=3)})
    )
    calls = []

    def invoke(call):
        calls.append(call)
        assert patch_id not in call.user
        return StructuredResult(
            parsed=call.schema.model_validate(
                {"repairs": [{"field_index": 0, "sources": [{"unit_index": 0, "ids": [patch_id]}]}]}
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    ctx = context(invoke, [{"name": "total"}], citation_repair=True)
    original = FieldOut(name="total", value="100", sources=[SourceRef(unit_index=0, ids=["p1:l0"])])
    call = LLMCall(
        stage="extraction",
        system="",
        user="",
        schema=StructuredResult,
        mock_context={"text": "=== PAGE 1 (unit 0) ===\nTotal [p1:l0]\n100 [p1:l1]"},
    )
    result = DocumentResult()
    repairer = CitationRepairer(ctx, layout)
    repaired = repairer.repair(call, [original], {"total": "string"}, {0}, result)
    assert len(calls) == 1 and repaired == [original]
    assert not repairer.repaired_ids and not result.raw_responses[-1]["updates"]


def test_unseen_value_does_not_trigger_a_repair_call():
    from docai.adapters.llm.base import LLMCall
    from docai.workflows.base import DocumentResult
    from docai.workflows.citation_repair import CitationRepairer

    ctx = context(
        lambda call: pytest.fail("Unseen content cannot authorize a repair"),
        [{"name": "total"}],
        citation_repair=True,
    )
    original = FieldOut(name="total", value="100", sources=[SourceRef(unit_index=0, ids=["p1:l0"])])
    call = LLMCall(
        stage="extraction",
        system="",
        user="",
        schema=StructuredResult,
        mock_context={"text": "=== PAGE 1 (unit 0) ===\nTotal [p1:l0]"},
    )
    repairer = CitationRepairer(ctx, fixture_layout())
    assert repairer.repair(call, [original], {"total": "string"}, {0}, DocumentResult()) == [
        original
    ]
    assert not repairer.attempted


def test_repair_cannot_use_a_table_header_to_reach_unsubmitted_cells():
    from docai.adapters.llm.base import LLMCall
    from docai.schemas.layout import Table, TableCell
    from docai.workflows.base import DocumentResult
    from docai.workflows.citation_repair import CitationRepairer

    layout = fixture_layout()
    page = layout.pages[0]
    page.tables = [
        Table(
            id="p1:t0",
            row_count=2,
            col_count=1,
            cells=[
                TableCell(
                    id="p1:t0:r0:c0", row=0, col=0, text="100", span=Span(offset=6, length=3)
                ),
                TableCell(
                    id="p1:t0:r1:c0", row=1, col=0, text="secret", span=Span(offset=10, length=6)
                ),
            ],
        )
    ]

    def invoke(call):
        assert "secret" not in call.user
        return StructuredResult(
            parsed=call.schema.model_validate(
                {"repairs": [{"field_index": 0, "sources": [{"unit_index": 0, "ids": ["p1:t0"]}]}]}
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    original = FieldOut(name="total", value="100", sources=[SourceRef(unit_index=0, ids=["p1:l0"])])
    call = LLMCall(
        stage="extraction",
        system="",
        user="",
        schema=StructuredResult,
        mock_context={"text": "Total [p1:l0]\n[table p1:t0]\n| 100 [p1:t0:r0:c0] |"},
    )
    repairer = CitationRepairer(context(invoke, [{"name": "total"}], citation_repair=True), layout)
    assert repairer.repair(call, [original], {"total": "string"}, {0}, DocumentResult()) == [
        original
    ]
    assert repairer.attempted and not repairer.repaired_ids


@pytest.mark.django_db
@pytest.mark.parametrize("legacy", [False, True])
def test_repaired_checkbox_survives_persistence_labels_export_and_promotion(
    project, dataset, admin, sample_workflow, w2_pdf, legacy
):
    from docai.models import GroundTruthLabel, SourceSpan, SourceUnit
    from docai.services import export, extraction_visualization, ingestion, labeling, review, runs

    layout = fixture_layout()
    layout.pages[0].selection_marks = [
        SelectionMark(
            id="p1:sm0", state="unselected", polygon=[0.1, 0.1, 0.2, 0.1, 0.2, 0.2, 0.1, 0.2]
        )
    ]

    def invoke(call):
        if call.stage == "citation_repair":
            return StructuredResult(
                parsed=call.schema.model_validate(
                    {
                        "repairs": [
                            {"field_index": 0, "sources": [{"unit_index": 0, "ids": ["p1:sm0"]}]}
                        ]
                    }
                ),
                raw_response="{}",
                model_deployment="fixture",
            )
        return response(
            call,
            [
                {
                    "name": "checkbox p1:sm0",
                    "value": "unselected",
                    "unit_index": 0,
                    "sources": [{"unit_index": 0, "ids": ["p1:l0"]}],
                }
            ],
        )

    result = ExtractStructured().process_document(
        context(invoke, [{"name": "checkbox p1:sm0"}], citation_repair=True), layout
    )
    value = result.fields[0]
    assert value.grounding is not None
    assert value.grounding["method"] == "selection_mark" and value.grounding["citation_repaired"]
    labels = extraction_visualization.collect_labels(result, layout)
    assert labels[0]["color"] == "blue" and labels[0]["citation_repaired"]
    doc = ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    SourceUnit.objects.create(document=doc, kind="page", index=0)
    run = runs.create_run(project, sample_workflow, dataset, admin)
    runs.persist_result(run, doc, result, layout)
    field = run.fields.get()
    span = field.spans.get()
    assert span.mapping_method == "selection_mark" and span.exceptions == ["citation_repair"]
    if legacy:
        span.mapping_method = "citation_repair:selection_mark"
        span.exceptions = []
        span.save()
    assert export.run_package(run)["fields"][0]["source"]["citation_repaired"]
    review.act_on_field(field, "accept", admin)
    label = labeling.promote_field_to_ground_truth(field, admin)
    assert label.mapping_method == "selection_mark+promoted"
    assert label.mapping_exceptions == ["citation_repair"]
    assert label.spans.get().mapping_method == "selection_mark"
    GroundTruthLabel._meta.get_field("mapping_method").clean(label.mapping_method, label)
    SourceSpan._meta.get_field("mapping_method").clean(
        label.spans.get().mapping_method, label.spans.get()
    )


@pytest.mark.django_db
@pytest.mark.parametrize("legacy", [False, True])
def test_false_checkbox_property_keeps_escaped_identity_without_locating_whole_list(
    project, dataset, admin, sample_workflow, w2_pdf, legacy
):
    from docai.models import SourceUnit
    from docai.services import export, extraction_visualization, ingestion, labeling, review, runs

    layout = fixture_layout()
    layout.pages[0].selection_marks = [
        SelectionMark(id="p1:sm0", state="unselected", polygon=layout.pages[0].words[0].polygon)
    ]
    value = '[{"a/b~c":false,"zero":0,"absent":null}]'

    def invoke(call):
        return response(
            call,
            [
                {
                    "name": "flags",
                    "value": value,
                    "property_sources": [
                        {"path": "/0/a~1b~0c", "sources": [{"unit_index": 0, "ids": ["p1:sm0"]}]}
                    ],
                }
            ],
        )

    result = ExtractStructured().process_document(
        context(invoke, [{"name": "flags", "type": "list"}]), layout
    )
    labels = extraction_visualization.collect_labels(result, layout)
    assert [(label["value"], label["color"]) for label in labels] == [
        (False, "green"),
        (0, "orange"),
    ]
    doc = ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    SourceUnit.objects.create(document=doc, kind="page", index=0)
    run = runs.create_run(project, sample_workflow, dataset, admin)
    runs.persist_result(run, doc, result, layout)
    field = run.fields.get()
    span = field.spans.get()
    assert span.mapping_method == "selection_mark" and span.exceptions == [
        "list_property_path=/0/a~1b~0c"
    ]
    if legacy:
        span.mapping_method = "list_property:selection_mark"
        span.save()
    exported = export.run_package(run)["fields"][0]["source"]["property_spans"]
    assert len(exported) == 1 and exported[0]["path"] == labels[0]["path"] == "/0/a~1b~0c"
    review.act_on_field(field, "accept", admin)
    label = labeling.promote_field_to_ground_truth(field, admin)
    assert label.expected_value == value and label.unit is None and not label.spans.exists()


def test_partial_line_marker_does_not_expand_unsubmitted_content_during_repair():
    from docai.adapters.llm.base import LLMCall
    from docai.workflows.base import DocumentResult
    from docai.workflows.citation_repair import CitationRepairer

    layout = fixture_layout()
    layout.pages[0].lines.append(
        Line(id="p1:l2", text="Private record 100", span=Span(offset=10, length=18))
    )

    def invoke(call):
        assert "Private record" not in call.user
        return StructuredResult(
            parsed=call.schema.model_validate(
                {"repairs": [{"field_index": 0, "sources": [{"unit_index": 0, "ids": ["p1:l2"]}]}]}
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    original = FieldOut(name="total", value="100", sources=[SourceRef(unit_index=0, ids=["p1:l0"])])
    call = LLMCall(
        stage="extraction",
        system="",
        user="",
        schema=StructuredResult,
        mock_context={"text": "Total [p1:l0]\n100 [p1:l1]\n100 [p1:l2]"},
    )
    repairer = CitationRepairer(context(invoke, [{"name": "total"}], citation_repair=True), layout)
    assert repairer.repair(call, [original], {"total": "string"}, {0}, DocumentResult()) == [
        original
    ]
    assert repairer.attempted and not repairer.repaired_ids


@pytest.mark.parametrize("cell_ref,applied", [("B1", True), ("C1", False)])
def test_spreadsheet_repairs_use_only_complete_submitted_cells(cell_ref, applied):
    from docai.adapters.llm.base import LLMCall
    from docai.schemas.layout import LayoutSheet, SheetCell
    from docai.workflows.base import DocumentResult
    from docai.workflows.citation_repair import CitationRepairer

    layout = LayoutDocument(
        document_id="sheet",
        source_format="xlsx",
        service="fixture",
        units=[
            LayoutSheet(
                index=0,
                name="Sheet",
                row_count=1,
                col_count=3,
                cells=[
                    SheetCell(id="s0:A1", ref="A1", row=1, col=1, value="Total"),
                    SheetCell(id="s0:B1", ref="B1", row=1, col=2, value="100"),
                    SheetCell(id="s0:C1", ref="C1", row=1, col=3, value="100"),
                ],
            )
        ],
    )

    def invoke(call):
        return StructuredResult(
            parsed=call.schema.model_validate(
                {
                    "repairs": [
                        {
                            "field_index": 0,
                            "sources": [{"unit_index": 0, "ids": [f"s0:{cell_ref}"]}],
                        }
                    ]
                }
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    original = FieldOut(name="total", value="100", sources=[SourceRef(unit_index=0, ids=["s0:A1"])])
    call = LLMCall(
        stage="extraction",
        system="",
        user="",
        schema=StructuredResult,
        mock_context={"text": "=== SHEET 'Sheet' (unit 0, 1x3) ===\nA1=Total | B1=100"},
    )
    repairer = CitationRepairer(context(invoke, [{"name": "total"}], citation_repair=True), layout)
    result = repairer.repair(call, [original], {"total": "string"}, {0}, DocumentResult())
    assert bool(repairer.repaired_ids) == applied
    assert result[0].value == original.value
    assert result[0].sources[0].ids == (["s0:B1"] if applied else ["s0:A1"])
