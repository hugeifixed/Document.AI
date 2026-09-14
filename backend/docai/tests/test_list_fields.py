"""Collection boundaries: no lost rows, false scalar grounding, or malformed corrections."""

import json
from types import SimpleNamespace

import pytest

from docai.exceptions import ValidationFailed
from docai.layout.reconcile import reconcile
from docai.models import ExtractedField, ReviewAction
from docai.schemas.llm import FieldOut, StructuredResult
from docai.serializers.core import FieldSerializer
from docai.services import export, ingestion, review, runs
from docai.tests.test_extraction_evidence_review import context, layout
from docai.validation.collections import LIST_REVIEW
from docai.validation.normalize import normalize_value, values_match
from docai.validation.rules import validate_field
from docai.workflows.extract_structured import ExtractStructured


@pytest.mark.parametrize(
    "value", ['[{"code":"001","amount":"12.30"}]', '["A", "a", null, true, 12.3]', "[]"]
)
def test_list_normalization_round_trips_and_ignores_text_options(value):
    normalized = normalize_value(value, "list")
    assert normalized is not None
    assert json.loads(normalized) == json.loads(value)
    assert values_match(value, json.dumps(json.loads(value), indent=2), "list")


@pytest.mark.parametrize(
    "value", ["oops", '{"amount":1}', "[NaN]", "[Infinity]", "[1e9999]", '[{"a":1,"a":2}]']
)
def test_invalid_list_never_matches_or_normalizes(value):
    assert normalize_value(value, "list") is None
    assert not values_match(value, value, "list")
    assert validate_field("any_collection", value, [], {}, "list").status == "failed"


def test_list_comparison_preserves_rows_values_types_and_order():
    for different in [
        '[{"amount":"1230"}]',
        '[{"amount":12.30}]',
        '[{"amount":"12.30"},{"amount":"12.30"}]',
    ]:
        assert not values_match('[{"amount":"12.30"}]', different, "list", "digits")
    assert not values_match('["A","B"]', '["B","A"]', "list")
    assert not values_match("[true]", "[1]", "list")
    assert validate_field("items", "[]", [{"kind": "required"}], {}, "list").status == "failed"


@pytest.mark.parametrize("value", ["[100]", '[{"amount":"100"}]', "not json", "[]"])
def test_any_list_requires_review_without_digit_grounding(value):
    def invoke(call):
        return StructuredResult(
            parsed=call.schema.model_validate(
                {
                    "fields": [
                        {
                            "name": "valid",
                            "value": value,
                            "confidence": 1,
                            "sources": [{"unit_index": 0, "ids": ["p1:w0"]}],
                        },
                        {
                            "name": "invalid",
                            "value": "100",
                            "confidence": 1,
                            "sources": [{"unit_index": 0, "ids": ["p1:w0"]}],
                        },
                    ]
                }
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    ctx = context("custom", invoke)
    ctx.config.schema_.fields[0].type = "list"
    result = ExtractStructured().process_document(ctx, layout())
    collection, scalar = result.fields
    assert collection.raw_value == value
    assert collection.grounding is None and collection.review_outcome == "human_review"
    assert LIST_REVIEW in collection.validation_messages
    assert scalar.grounding and scalar.review_outcome == "auto_accept"


def test_reconciliation_does_not_merge_rows_or_lose_disagreements():
    first = FieldOut(name="entries", value='[{"box":"1","amount":"100"}]', confidence=1)
    same = FieldOut(name="entries", value='[ {"amount":"100", "box":"1"} ]', confidence=0.9)
    second = FieldOut(name="entries", value='[{"box":"2","amount":"200"}]', confidence=0.8)
    assert not reconcile([[first], [same]], "highest_score", {"entries": "list"})[
        "entries"
    ].conflict
    result = reconcile([[first], [second]], "highest_score", {"entries": "list"})["entries"]
    assert result.conflict and result.candidates == [first, second]
    assert result.field.value == first.value


@pytest.mark.django_db
def test_list_review_export_and_masking(project, dataset, admin, viewer, sample_workflow, w2_pdf):
    document = ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = runs.create_run(project, sample_workflow, dataset, admin)
    raw = '[{"box":"01","amount":"12.30"}]'
    field = ExtractedField.objects.create(
        run=run,
        document=document,
        name="entries",
        field_type="list",
        raw_value=raw,
        normalized_value=normalize_value(raw, "list"),
        list_candidates=[{"value": raw}],
    )
    for action in ("correct", "accept"):
        if action == "accept":
            field.raw_value = "bad json"
        with pytest.raises(ValidationFailed):
            review.act_on_field(field, action, admin, value="bad json")
    assert not ReviewAction.objects.filter(field=field).exists()
    field.raw_value = raw
    review.act_on_field(field, "correct", admin, value='[{"box":"01","amount":"13.40"}]')
    field.refresh_from_db()
    assert field.raw_value == raw and field.review_status == "corrected"
    packaged = export.run_package(run)["fields"][0]
    assert json.loads(packaged["normalized_value"]) == json.loads(raw)
    assert packaged["list_candidates"] == [{"value": raw}]
    assert "13.40" in export.rows_to_csv([packaged]).decode("utf-8-sig")
    masked = FieldSerializer(field, context={"request": SimpleNamespace(user=viewer)}).data
    assert raw not in str(masked["list_candidates"])


@pytest.mark.django_db
def test_conflicting_list_candidates_survive_persistence(
    project, dataset, admin, sample_workflow, w2_pdf
):
    from docai.workflows.base import DocumentResult, FieldResultData

    document = ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = runs.create_run(project, sample_workflow, dataset, admin)
    candidates: list[dict] = [
        {"name": "entries", "value": json.dumps([{"row": i}]), "sources": []} for i in range(7)
    ]
    result = DocumentResult(
        fields=[
            FieldResultData(
                name="entries",
                field_type="list",
                raw_value=candidates[0]["value"],
                normalized_value=candidates[0]["value"],
                candidates=candidates,
                conflict=True,
                score=1,
                source_text="",
                method="llm",
                strategy="whole",
                fallback_used="",
                model_deployment="test",
                prompt=None,
                schema=None,
                api_version="",
                validation_status="warning",
                validation_messages=[],
                suggested_correction=None,
                grounding=None,
                review_outcome="human_review",
            )
        ]
    )
    runs.persist_result(run, document, result, layout())
    saved = run.fields.get()
    assert saved.list_candidates == candidates
    assert saved.review_status == "needs_review" and not saved.grounded
    assert export.run_package(run)["fields"][0]["list_candidates"] == candidates


def test_pipeline_flags_conflicting_chunk_lists_even_with_permissive_routing():
    from docai.validation.collections import LIST_CONFLICT

    calls = 0

    def invoke(call):
        nonlocal calls
        calls += 1
        return StructuredResult(
            parsed=call.schema.model_validate(
                {"fields": [{"name": "valid", "value": f"[{calls * 100}]", "confidence": 1}]}
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    ctx = context("custom", invoke)
    ctx.config.schema_.fields[0].type = "list"
    ctx.config.chunking.strategy = "page"
    doc = layout()
    doc.units.append(doc.units[0].model_copy(update={"index": 1, "number": 2}))
    result = ExtractStructured().process_document(ctx, doc)
    field = result.fields[0]
    assert calls == 2
    assert field.review_outcome == "human_review" and field.grounding is None
    assert LIST_CONFLICT in field.validation_messages
    assert [candidate["value"] for candidate in field.candidates] == ["[100]", "[200]"]
