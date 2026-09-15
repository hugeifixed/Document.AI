"""Synthetic Azure-shaped checkbox evidence and real run/API persistence."""

from types import SimpleNamespace
from typing import Literal

import pytest

from docai.adapters.llm.mock import MockStructuredLLM
from docai.schemas.layout import LayoutDocument, LayoutPage, SelectionMark, Word
from docai.schemas.llm import FieldOut, SourceRef, StructuredResult
from docai.services import governance, ingestion, layouts, run_execution, runs
from docai.synthetic.pdfwriter import write_pdf
from docai.workflows.evidence import ground

BOX = [0.12, 0.25, 0.14, 0.25, 0.14, 0.27, 0.12, 0.27]


@pytest.fixture
def checkbox_layout():
    states: list[Literal["selected", "unselected"]] = ["selected", "unselected"]
    return LayoutDocument(
        document_id="checkboxes",
        source_format="pdf",
        service="azure_document_intelligence",
        units=[
            LayoutPage(
                index=i,
                number=i + 1,
                width=8.5,
                height=11,
                unit="inch",
                content="Consent selected unselected",
                words=[
                    Word(id=f"p{i + 1}:w{j}", text=text, polygon=BOX)
                    for j, text in enumerate(["Consent", "selected", "unselected"])
                ],
                selection_marks=[
                    SelectionMark(id=f"p{i + 1}:sm{j}", state=state, polygon=BOX)
                    for j, state in enumerate(states)
                ],
            )
            for i in range(3)
        ],
    )


def checkbox_field(state="selected", citation="explicit"):
    mark_id = f"p3:sm{int(state == 'unselected')}"
    return FieldOut(
        name=f"checkbox {mark_id}" if citation == "name" else "Consent",
        value=state,
        confidence=0.93,
        evidence=f"[checkbox {mark_id}: {state}]" if citation == "evidence" else "",
        sources=[SourceRef(unit_index=2, ids=[mark_id])] if citation == "explicit" else [],
    )


@pytest.mark.parametrize("state", ["selected", "unselected"])
@pytest.mark.parametrize("citation", ["explicit", "name", "evidence"])
def test_verified_mark_retains_original_identity_and_polygon(checkbox_layout, state, citation):
    field = checkbox_field(state, citation)
    field.value = f"  {state.upper()}  "
    if citation != "explicit":
        field.name = f" {field.name.upper()} "
        field.evidence = f" {field.evidence.upper()} "
    hit = ground(checkbox_layout, field, None, allowed_indexes={2})
    assert hit == {
        "unit_index": 2,
        "word_ids": [f"p3:sm{int(state == 'unselected')}"],
        "polygon": BOX,
        "method": "selection_mark",
        "score": 1.0,
        "offset_start": None,
        "offset_end": None,
    }
    assert field.confidence == 0.93


@pytest.mark.parametrize(
    "failure",
    [
        "unknown",
        "wrong_page",
        "hint",
        "scope",
        "excluded",
        "state",
        "yes",
        "contradictory_marker",
        "contradictory_state",
        "multiple_explicit",
        "multiple_canonical",
        "malformed_marker",
        "text_citation",
        "page_citation",
        "duplicate_mark",
        "page_number",
    ],
)
def test_failed_claim_never_falls_back_to_repeated_state_text(checkbox_layout, failure):
    field = checkbox_field(citation="evidence")
    hint, allowed = None, None
    if failure == "unknown":
        field.evidence = "[checkbox p3:sm99: selected]"
    elif failure == "wrong_page":
        field.sources = [SourceRef(unit_index=0, ids=["p3:sm0"])]
    elif failure == "hint":
        hint = 0
    elif failure == "scope":
        allowed = {0, 1}
    elif failure == "excluded":
        checkbox_layout.pages[2].excluded_from_analysis = True
    elif failure == "state":
        checkbox_layout.pages[2].selection_marks[0].state = "unselected"
    elif failure == "yes":
        field.value = "yes"
    elif failure == "contradictory_marker":
        field.sources = [SourceRef(unit_index=0, ids=["p1:sm0"])]
    elif failure == "contradictory_state":
        field.evidence = "[checkbox p3:sm0: unselected]"
    elif failure == "multiple_explicit":
        field.sources = [SourceRef(unit_index=2, ids=["p3:sm0", "p3:sm1"])]
    elif failure == "multiple_canonical":
        field.name = "checkbox p1:sm0"
    elif failure == "malformed_marker":
        field.evidence += " guessed"
    elif failure == "text_citation":
        field.sources = [SourceRef(unit_index=2, ids=["p3:w1"])]
    elif failure == "page_citation":
        field.sources = [SourceRef(unit_index=0)]
    elif failure == "duplicate_mark":
        checkbox_layout.pages[2].selection_marks.append(checkbox_layout.pages[2].selection_marks[0])
    elif failure == "page_number":
        checkbox_layout.pages[2].number = 1
    assert ground(checkbox_layout, field, hint, allowed_indexes=allowed) is None


@pytest.mark.parametrize(
    "polygon",
    [
        [],
        [0.1, 0.2],
        [0.1] * 8,
        [0, 0, 1, 0, 1, 0, 0, 0],
        [0, 0, 1, 1, 1, 0, 0, 1],
        [0, 0, 1, 0, 1.1, 1, 0, 1],
        [-0.1, 0, 1, 0, 1, 1, 0, 1],
        [float("nan"), *BOX[1:]],
        [float("inf"), *BOX[1:]],
    ],
)
@pytest.mark.parametrize("citation", ["explicit", "name"])
def test_bad_geometry_is_unverified_even_with_matching_text(checkbox_layout, polygon, citation):
    checkbox_layout.pages[2].selection_marks[0].polygon = polygon
    assert ground(checkbox_layout, checkbox_field(citation=citation), None) is None


def test_explicit_mark_citation_cannot_substitute_another_matching_mark(checkbox_layout):
    field = checkbox_field()
    checkbox_layout.pages[2].selection_marks[0].polygon = []
    assert ground(checkbox_layout, field, None) is None
    text = FieldOut(
        name="Status", value="selected", sources=[SourceRef(unit_index=2, ids=["p3:w1"])]
    )
    hit = ground(checkbox_layout, text, None)
    assert hit is not None and hit["method"] == "exact"


@pytest.fixture
def checkbox_document(checkbox_layout, dataset, admin, monkeypatch):
    document = ingestion.ingest_upload(
        dataset,
        "consent.pdf",
        write_pdf([["Consent selected unselected"]] * 3),
        user=admin,
    )
    monkeypatch.setattr(
        layouts,
        "get_layout_provider_for_format",
        lambda *_, **kwargs: SimpleNamespace(
            key="fixture",
            supports_ocr=False,
            analyze=lambda *args, **kwargs: checkbox_layout,
        ),
    )
    return document


def run_checkbox(
    document,
    project,
    admin,
    monkeypatch,
    field,
    mode,
    *,
    strategy="whole_document",
    target_chunk=None,
):
    config = {
        "mode": mode,
        "chunking": {"strategy": strategy},
        "schema": {"name": "consent", "fields": [{"name": field.name}, {"name": "Heading"}]},
    }
    workflow = governance.create_workflow_version(
        project, "checkbox", "extract_structured", config, admin
    )

    def invoke(self, call):
        fields = [field] if target_chunk is None or call.chunk_index == target_chunk else []
        if call.chunk_index == 0:
            fields = [*fields, FieldOut(name="Heading", value="Consent", confidence=0.95)]
        return StructuredResult(
            parsed=call.schema.model_validate({"pairs" if mode == "default" else "fields": fields}),
            raw_response="{}",
            model_deployment="synthetic-provider",
        )

    monkeypatch.setattr(MockStructuredLLM, "invoke", invoke)
    return run_execution.execute_run(runs.create_run(project, workflow, document.dataset, admin).pk)


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["default", "custom"])
@pytest.mark.parametrize("state", ["selected", "unselected"])
@pytest.mark.parametrize("citation", ["explicit", "name", "evidence"])
def test_run_persists_and_serializes_verified_checkbox(
    checkbox_document,
    project,
    admin,
    api,
    monkeypatch,
    mode,
    state,
    citation,
):
    output = checkbox_field(state, citation)
    run = run_checkbox(checkbox_document, project, admin, monkeypatch, output, mode)
    field = run.fields.get(name=output.name)
    assert field.grounded and field.raw_value == state and field.score == 0.93
    assert field.review_status == "auto_accepted"
    span = field.spans.get()
    assert (
        span.unit.index == 2 and span.unit.layout_artifact_id == run.items.get().layout_artifact_id
    )
    assert span.word_ids == [f"p3:sm{int(state == 'unselected')}"]
    assert span.mapping_method == "selection_mark" and span.match_score == 1.0
    assert span.polygon == BOX
    data = api.get(f"/api/v1/fields/{field.pk}/").json()["data"]
    assert data["score"] == 0.93 and data["raw_value"] == state
    assert data["spans"][0]["polygon"] == BOX
    assert data["spans"][0]["mapping_method"] == "selection_mark"
    assert data["spans"][0]["word_ids"] == span.word_ids
    field.review_status = "accepted"
    field.save(update_fields=["review_status"])
    promoted = api.post(f"/api/v1/fields/{field.pk}/promote/", {}, format="json")
    assert promoted.status_code == 201
    label = promoted.json()["data"]
    assert label["spans"][0]["word_ids"] == span.word_ids
    assert label["spans"][0]["polygon"] == BOX
    assert label["spans"][0]["mapping_method"] == "selection_mark"


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["default", "custom"])
@pytest.mark.parametrize("failure", ["state", "geometry", "chunk_scope"])
def test_run_retains_unverified_field_and_model_score_for_review(
    checkbox_document,
    checkbox_layout,
    project,
    admin,
    monkeypatch,
    mode,
    failure,
):
    output = checkbox_field(citation="evidence")
    if failure == "state":
        checkbox_layout.pages[2].selection_marks[0].state = "unselected"
    if failure == "geometry":
        checkbox_layout.pages[2].selection_marks[0].polygon = []
    run = run_checkbox(
        checkbox_document,
        project,
        admin,
        monkeypatch,
        output,
        mode,
        strategy="page" if failure == "chunk_scope" else "whole_document",
        target_chunk=0 if failure == "chunk_scope" else None,
    )
    field = run.fields.get(name=output.name)
    assert not field.grounded and not field.spans.exists()
    assert field.raw_value == output.value and field.score == output.confidence
    assert field.review_status == "needs_review"
    assert run.fields.get(name="Heading").grounded


@pytest.mark.django_db
@pytest.mark.parametrize(
    "policy", ["highest_score", "first_non_null", "majority", "conflicts_to_review"]
)
@pytest.mark.parametrize("in_scope", [True, False])
@pytest.mark.parametrize("tied_confidence", [True, False])
def test_reconciliation_preserves_chosen_checkbox_chunk_scope(
    checkbox_document,
    project,
    admin,
    monkeypatch,
    policy,
    in_scope,
    tied_confidence,
):
    workflow = governance.create_workflow_version(
        project,
        "reconciled-checkbox",
        "extract_unstructured",
        {
            "chunking": {"strategy": "page"},
            "reconciliation": {"policy": policy},
            "schema": {"name": "consent", "fields": [{"name": "Consent"}]},
        },
        admin,
    )

    def invoke(self, call):
        # Both assertions point to page 3. The winning candidate must retain the
        # scope of its original call, even when conflict routing copies it.
        field = checkbox_field(citation="evidence")
        field.confidence = (
            0.93 if tied_confidence or call.chunk_index == (2 if in_scope else 0) else 0.6
        )
        if call.chunk_index == 1:
            field.value = "unselected"
            field.evidence = "[checkbox p3:sm1: unselected]"
        if in_scope and call.chunk_index == 0:
            field.value = None
        return StructuredResult(
            parsed=call.schema.model_validate({"fields": [field]}),
            raw_response="{}",
            model_deployment="synthetic-provider",
        )

    monkeypatch.setattr(MockStructuredLLM, "invoke", invoke)
    run = run_execution.execute_run(
        runs.create_run(project, workflow, checkbox_document.dataset, admin).pk
    )
    field = run.fields.get()
    # first_non_null selects the earlier unselected candidate in the in-scope
    # fixture; majority ties also favor that first candidate.
    # Equal confidence must retain the first non-null candidate and its scope.
    expected_grounded = (
        in_scope and not tied_confidence and policy in {"highest_score", "conflicts_to_review"}
    )
    assert field.grounded == expected_grounded
    assert field.spans.exists() == expected_grounded
    assert field.review_status == "needs_review"
    if policy == "conflicts_to_review":
        assert field.score == 0.0  # existing reconciliation policy is unchanged


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["default", "custom"])
def test_verified_location_does_not_raise_model_confidence_or_bypass_review(
    checkbox_document,
    project,
    admin,
    monkeypatch,
    mode,
):
    output = checkbox_field()
    output.confidence = 0.52
    run = run_checkbox(checkbox_document, project, admin, monkeypatch, output, mode)
    field = run.fields.get(name=output.name)
    assert field.grounded and field.spans.get().match_score == 1.0
    assert field.score == 0.52 and field.review_status == "needs_review"


def test_consistent_page_and_mark_citations_and_canonical_source_quote(checkbox_layout):
    field = checkbox_field()
    field.sources.append(SourceRef(unit_index=2, quote="[checkbox p3:sm0: selected]"))
    hit = ground(checkbox_layout, field, 2)
    assert hit is not None and hit["word_ids"] == ["p3:sm0"]
    field.sources[-1].quote = "[checkbox p3:sm0: unselected]"
    assert ground(checkbox_layout, field, 2) is None
