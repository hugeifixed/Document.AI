"""Boolean extraction keeps cited source text separate from its normalized meaning."""

from types import SimpleNamespace

import pytest

from docai.schemas.config import ExtractStructuredConfig
from docai.schemas.layout import LayoutDocument, LayoutPage, SelectionMark, Word
from docai.schemas.llm import StructuredResult
from docai.services.extraction_visualization import collect_labels
from docai.validation.normalize import normalize_value, values_match
from docai.validation.rules import validate_field
from docai.workflows.base import PromptRef, WorkflowContext
from docai.workflows.extract_structured import ExtractStructured
from docai.workflows.prompts import EXTRACT_SYSTEM, EXTRACT_USER


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("Yes", "true"),
        (" No ", "false"),
        ("Y", "true"),
        ("N", "false"),
        ("TRUE", "true"),
        ("False", "false"),
        ("1", "true"),
        ("0", "false"),
        ("checked", "true"),
        ("unchecked", "false"),
        ("selected", "true"),
        ("unselected", "false"),
        (True, "true"),
        (False, "false"),
        (None, None),
        ("", None),
        ("   ", None),
        ("unknown", None),
        ("N/A", None),
        ("not provided", None),
    ],
)
def test_only_explicit_boolean_answers_normalize(raw, normalized):
    assert normalize_value(raw, "boolean") == normalized
    if normalized is not None:
        assert values_match(raw, normalized, "boolean")


@pytest.mark.parametrize("raw", ["unknown", "N/A", "not provided"])
def test_unknown_answers_cannot_validate_or_match_false(raw):
    outcome = validate_field("binary_flag", raw, [], {}, "boolean")
    assert outcome.status == "failed"
    assert not values_match(raw, "No", "boolean")
    assert not values_match(raw, raw, "boolean")


@pytest.mark.parametrize(
    ("raw", "normalized", "checkbox"),
    [
        ("Yes", "true", False),
        ("No", "false", False),
        ("selected", "true", True),
        ("unselected", "false", True),
        (None, None, False),
        ("unknown", None, False),
    ],
)
def test_shared_extraction_preserves_raw_answer_citation_and_false_label(raw, normalized, checkbox):
    polygon = [0.1, 0.1, 0.2, 0.1, 0.2, 0.2, 0.1, 0.2]
    source_id = "p1:sm0" if checkbox else "p1:w0"
    evidence = f"[checkbox {source_id}: {raw}]" if checkbox else raw or ""
    doc = LayoutDocument(
        document_id="synthetic-binary",
        source_format="pdf",
        service="fixture",
        units=[
            LayoutPage(
                index=0,
                number=1,
                content="Feature enabled: " + (raw or ""),
                words=[Word(id=source_id, text=raw, polygon=polygon)]
                if raw and not checkbox
                else [],
                selection_marks=[SelectionMark(id=source_id, state=raw, polygon=polygon)]
                if checkbox
                else [],
            )
        ],
    )
    calls = []

    def invoke(call):
        calls.append(call)
        # The actual extraction request must distinguish raw printed answers
        # from the normalized result, even with a legacy true/false instruction.
        assert "raw value" in call.user.lower()
        assert "verbatim" in call.user.lower()
        assert "normalized" in call.user.lower()
        assert "Yes" in call.user and "No" in call.user
        return StructuredResult(
            parsed=call.schema.model_validate(
                {
                    "fields": [
                        {
                            "name": "binary_flag",
                            "value": raw,
                            "confidence": 1 if raw else None,
                            "evidence": evidence,
                            "sources": [{"unit_index": 0, "ids": [source_id], "quote": evidence}]
                            if raw
                            else [],
                        }
                    ]
                }
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    config = ExtractStructuredConfig.model_validate(
        {
            "mode": "custom",
            "schema": {
                "name": "any_binary_form",
                "fields": [
                    {
                        "name": "binary_flag",
                        "description": "Whether the feature is enabled.",
                        "type": "boolean",
                        "guidance": "Return true or false only when explicitly indicated; otherwise null.",
                    }
                ],
            },
        }
    )
    ctx = WorkflowContext(
        workflow_type="extract_structured",
        config=config,
        llm=SimpleNamespace(key="fixture", invoke=invoke),
        prompts={"extraction": PromptRef("extraction", 1, EXTRACT_SYSTEM, EXTRACT_USER)},
        layout_adapter_key="fixture",
    )
    result = ExtractStructured().process_document(ctx, doc)
    field = result.fields[0]
    assert len(calls) == 1
    assert field.raw_value == raw and field.normalized_value == normalized
    assert field.validation_status == ("failed" if raw == "unknown" else "passed")
    if raw == "unknown":
        assert field.review_outcome == "human_review"
    labels = collect_labels(result, doc)
    if raw is None:
        assert field.grounding is None and labels == []
    else:
        assert field.grounding is not None
        assert field.grounding["word_ids"] == [source_id]
        assert len(labels) == 1 and labels[0]["value"] == raw and labels[0]["boxed"]
