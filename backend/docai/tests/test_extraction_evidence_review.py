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


@pytest.mark.parametrize("mode", ["default", "custom"])
def test_scalar_search_preserves_generic_chunk_and_schema_segment_scope(mode):
    """An uncited scalar may search its schema segment, but never a generic sibling chunk."""
    doc = layout()
    doc.units[0].content = "Header only"
    doc.units[0].words = []
    doc.units.append(
        LayoutPage(
            index=1,
            number=2,
            content="Total 100",
            words=[Word(id="p2:w0", text="100", polygon=[0.1, 0.1, 0.2, 0.1, 0.2, 0.2, 0.1, 0.2])],
        )
    )

    def invoke(call):
        fields = (
            [{"name": "valid", "value": "100", "confidence": 1}] if call.chunk_index == 0 else []
        )
        return StructuredResult(
            parsed=call.schema.model_validate({"pairs" if mode == "default" else "fields": fields}),
            raw_response="{}",
            model_deployment="fixture",
        )

    ctx = context(mode, invoke)
    ctx.config.chunking.strategy = "page"
    result = ExtractStructured().process_document(ctx, doc)
    field = next(field for field in result.fields if field.name == "valid")
    assert result.extraction_chunks == 2
    assert field.raw_value == "100"
    if mode == "custom":
        assert field.grounding is not None
        assert field.grounding["unit_index"] == 1
        assert field.grounding["word_ids"] == ["p2:w0"]
    else:
        assert field.grounding is None


def test_reconciliation_copy_keeps_invalid_original_evidence_and_value():
    from docai.workflows.extraction_core import run_extraction

    doc = layout()
    doc.units.append(LayoutPage(index=1, number=2, content="Total 200"))

    def invoke(call):
        first = call.chunk_index == 0
        return StructuredResult(
            parsed=call.schema.model_validate(
                {
                    "fields": [
                        {
                            "name": "valid",
                            "value": "100" if first else "200",
                            "confidence": 0.95 if first else 0.9,
                            "sources": [{"unit_index": 0, "ids": ["p1:invented"]}] if first else [],
                        }
                    ]
                }
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    ctx = context("custom", invoke)
    ctx.config.chunking.strategy = "page"
    result = run_extraction(
        ctx,
        doc,
        ctx.config.schema_,
        document_type=None,
        reconciliation_policy="conflicts_to_review",
    )
    field = result.fields[0]
    assert field.raw_value == "100"
    assert field.score == 0 and field.conflict
    assert len(field.candidates) == 2
    assert field.grounding is None
    assert field.validation_status == "failed"
    assert field.review_outcome == "human_review"
    assert any("Verify this value" in message for message in field.validation_messages)


def test_generic_repeated_name_preserves_each_candidate_trust():
    def invoke(call):
        return StructuredResult(
            parsed=call.schema.model_validate(
                {
                    "pairs": [
                        {
                            "name": " valid ",
                            "value": "100",
                            "confidence": 1,
                            "sources": [{"unit_index": 0, "ids": ["p1:w0"]}],
                        },
                        {
                            "name": "VALID",
                            "value": "200",
                            "confidence": 1,
                            "sources": [{"unit_index": 0, "ids": ["p1:invented"]}],
                        },
                    ]
                }
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    result = ExtractStructured().process_document(context("default", invoke), layout())
    assert len(result.fields) == 2
    field, invalid = result.fields
    assert field.name == "valid" and field.raw_value == "100"
    assert field.grounding is not None
    assert field.validation_status == "not_run"
    assert field.review_outcome == "auto_accept"
    assert invalid.name == "VALID" and invalid.raw_value == "200"
    assert invalid.grounding is None
    assert invalid.validation_status == "failed"
    assert invalid.review_outcome == "human_review"
    assert "1 fields need evidence review" in result.warnings[0]


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["default", "custom"])
def test_partial_rejected_extraction_retains_good_results_but_blocks_delivery(
    project, dataset, admin, w2_pdf, monkeypatch, mode
):
    from io import BytesIO

    from pypdf import PdfReader, PdfWriter

    from docai.models import ProcessingCheckpoint
    from docai.services.journey import run_guidance

    reader, writer = PdfReader(BytesIO(w2_pdf.data)), PdfWriter()
    writer.add_page(reader.pages[0])
    writer.add_page(reader.pages[0])
    data = BytesIO()
    writer.write(data)
    ingestion.ingest_upload(dataset, "two-forms.pdf", data.getvalue(), user=admin)
    workflow = governance.create_workflow_version(
        project,
        "Partial extraction",
        "extract_structured",
        {
            "mode": mode,
            "schema": {"name": "totals", "fields": [{"name": "total"}]},
            "chunking": {"strategy": "page"},
            "routing": [{"when": {"min_score": 0}, "outcome": "auto_accept"}],
        },
        admin,
    )

    def invoke(self, call):
        if call.chunk_index == 1:
            raise InvalidModelOutput()
        return StructuredResult(
            parsed=call.schema.model_validate(
                {
                    "pairs" if mode == "default" else "fields": [
                        {"name": "total", "value": "100", "confidence": 1},
                    ],
                }
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    monkeypatch.setattr(MockStructuredLLM, "invoke", invoke)
    run = run_execution.execute_run(runs.create_run(project, workflow, dataset, admin).pk)
    item = run.items.get()
    assert item.status == "failed" and run.status == "failed"
    assert item.error_code == "INCOMPLETE_EXTRACTION" and not item.retryable
    assert run.fields.get().raw_value == "100"
    assert not run.fields.filter(review_status="needs_review").exists()
    assert ProcessingCheckpoint.objects.filter(run_item=item, kind="llm_output").count() == 1
    assert run.warnings and not run_guidance(run)["export_ready"]
