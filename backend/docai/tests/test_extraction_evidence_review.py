"""Retain usable extraction output without granting trust to invalid citations."""

import json
from types import SimpleNamespace

import pytest

from docai.adapters.llm.mock import MockStructuredLLM
from docai.exceptions import InvalidModelOutput
from docai.schemas.config import ExtractStructuredConfig
from docai.schemas.layout import LayoutDocument, LayoutPage, Word
from docai.schemas.llm import StructuredResult
from docai.services import governance, ingestion, run_execution, runs
from docai.services.llm_debug import evidence_debug_capture
from docai.workflows.base import PromptRef, WorkflowContext
from docai.workflows.extract_structured import ExtractStructured


def context(mode, invoke, capture=None):
    return WorkflowContext(
        workflow_type="extract_structured",
        config=ExtractStructuredConfig.model_validate(
            {
                "mode": mode,
                "schema": {"name": "totals", "fields": [{"name": "valid"}, {"name": "invalid"}]},
                # Even permissive routing cannot accept an invalid citation.
                "routing": [{"when": {"min_score": 0}, "outcome": "auto_accept"}],
            }
        ),
        llm=SimpleNamespace(key="synthetic", invoke=invoke),
        prompts={
            stage: PromptRef(stage, 1, "", "{content}") for stage in ("generic_kv", "extraction")
        },
        layout_adapter_key="fixture",
        debug_capture=capture,
    )


def layout():
    return LayoutDocument(
        document_id="synthetic",
        source_format="pdf",
        service="fixture",
        units=[
            LayoutPage(
                index=0,
                number=1,
                content="Total 100",
                words=[
                    Word(id="p1:w0", text="100", polygon=[0.1, 0.1, 0.2, 0.1, 0.2, 0.2, 0.1, 0.2])
                ],
            )
        ],
    )


@pytest.mark.parametrize("mode", ["default", "custom"])
def test_invalid_citation_retains_value_for_review_and_preserves_valid_neighbor(mode):
    captures: list[dict] = []

    def invoke(call):
        return StructuredResult(
            parsed=call.schema.model_validate(
                {
                    "pairs" if mode == "default" else "fields": [
                        {
                            "name": name,
                            "value": "100",
                            "confidence": 1,
                            "unit_index": 0,
                            "sources": [{"unit_index": 0, "ids": [source]}],
                        }
                        for name, source in [("valid", "p1:w0"), ("invalid", "p1:invented")]
                    ]
                }
            ),
            raw_response="test response",
            model_deployment="fixture",
        )

    result = ExtractStructured().process_document(context(mode, invoke, captures.append), layout())
    good, bad = result.fields
    assert good.name == "valid" and good.grounding is not None
    assert good.grounding["word_ids"] == ["p1:w0"]
    assert good.review_outcome == "auto_accept"
    assert bad.raw_value == "100" and bad.grounding is None
    assert bad.review_outcome == "human_review" and bad.validation_status == "failed"
    assert "Verify this value" in bad.validation_messages[0]
    assert result.rejected_extraction_chunks == 0
    assert "INVALID_SOURCE_REFERENCE" in result.warnings[0]
    assert captures[0]["issues"] == [
        {"field_index": 1, "unit_index": 0, "validation_reason": "unknown_source"}
    ]
    assert captures[0]["allowed_source_ids"] == {"0": ["p1:w0"]}


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["default", "custom"])
def test_every_rejected_chunk_fails_the_item_and_run(
    project, dataset, admin, w2_pdf, monkeypatch, mode
):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    workflow = governance.create_workflow_version(
        project,
        "Invalid responses",
        "extract_structured",
        {
            "mode": mode,
            "schema": {"name": "totals", "fields": [{"name": "total"}]},
        },
        admin,
    )

    def invoke(self, call):
        raise InvalidModelOutput()

    monkeypatch.setattr(MockStructuredLLM, "invoke", invoke)
    run = run_execution.execute_run(runs.create_run(project, workflow, dataset, admin).pk)
    item = run.items.get()
    assert run.status == "failed" and item.status == "failed"
    assert item.error_code == "INVALID_MODEL_OUTPUT" and not item.retryable
    assert not run.fields.exists()
    assert run.warnings


@pytest.mark.parametrize("debug,enabled", [(False, True), (True, False), (True, True)])
def test_local_debug_capture_is_explicit_and_outside_media(settings, tmp_path, debug, enabled):
    settings.DEBUG = debug
    settings.DOCAI = {**settings.DOCAI, "LLM_DEBUG_CAPTURE": enabled}
    settings.DOCAI_DATA_DIR = tmp_path
    capture = evidence_debug_capture(SimpleNamespace(run_id="run", pk="item", attempts=2))
    if not (debug and enabled):
        assert capture is None and not list(tmp_path.iterdir())
        return
    capture({"raw_response": "synthetic sensitive value", "issues": [{"field_index": 1}]})
    files = list((tmp_path / "debug" / "llm" / "run" / "item").glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["attempt"] == 2 and payload["raw_response"] == "synthetic sensitive value"
    assert not (tmp_path / "media").exists()


def test_debug_capture_failure_does_not_discard_extraction():
    def capture(payload):
        raise OSError("unavailable")

    def invoke(call):
        return StructuredResult(
            parsed=call.schema.model_validate(
                {
                    "pairs": [
                        {
                            "name": "total",
                            "value": "100",
                            "sources": [{"unit_index": 99, "ids": []}],
                        }
                    ]
                }
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    result = ExtractStructured().process_document(context("default", invoke, capture), layout())
    assert result.fields[0].review_outcome == "human_review"
