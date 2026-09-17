"""Realistic long sections retain citations without exceeding extraction input limits."""

import json
import re

import pytest
from pydantic import ValidationError

from docai.exceptions import ContextLimitExceeded
from docai.layout.chunk import plan_chunks
from docai.schemas.config import ChunkingConfig
from docai.schemas.llm import ExtractionOut, StructuredResult
from docai.tests.test_extraction_evidence_review import context, layout
from docai.workflows.extract_structured import ExtractStructured
from docai.workflows.extraction_core import run_extraction


@pytest.mark.parametrize("strategy", ["context_length", "semantic"])
def test_long_note_bounds_headers_overlap_and_preserves_every_source(strategy):
    # No blank lines: a single legal clause must not bypass the semantic budget.
    ids = [f"p4:w{i}" for i in range(600)]
    note = "=== PAGE 4 (unit 3) ===\n" + " ".join(
        f"payment{i} [{source}]" for i, source in enumerate(ids)
    )
    plan = plan_chunks(
        [note], ChunkingConfig(strategy=strategy, chunk_chars=2000, overlap_chars=250)
    )
    assert len(plan.chunks) > 5
    assert all(len(chunk.text) <= 2000 for chunk in plan.chunks)
    assert all("=== PAGE 4 (unit 3) ===" in chunk.text for chunk in plan.chunks)
    assert set(ids) <= set(re.findall(r"\[(p4:w\d+)\]", "\n".join(c.text for c in plan.chunks)))
    assert all(chunk.continuation for chunk in plan.chunks[1:])


def test_request_budget_reserves_prompt_and_schema_overhead():
    plan = plan_chunks(
        ["=== PAGE 1 (unit 0) ===\n" + "amount " * 1200],
        ChunkingConfig(
            strategy="semantic", chunk_chars=4000, overlap_chars=100, max_request_chars=3000
        ),
        prompt_overhead_chars=1100,
    )
    assert len(plan.chunks) > 1
    assert all(len(chunk.text) + 1100 <= 3000 for chunk in plan.chunks)
    assert all(chunk.meta["prompt_overhead_chars"] == 1100 for chunk in plan.chunks)


@pytest.mark.parametrize(
    "config,overhead",
    [
        ({"strategy": "page", "max_request_chars": 2000}, 10),
        ({"strategy": "whole_document", "max_request_chars": 2000}, 2100),
        (
            {
                "strategy": "semantic",
                "chunk_chars": 2000,
                "overlap_chars": 1500,
                "max_request_chars": 2000,
            },
            600,
        ),
    ],
)
def test_input_that_cannot_fit_fails_before_provider_submission(config, overhead):
    with pytest.raises(ContextLimitExceeded):
        plan_chunks(["x" * 4000], ChunkingConfig(**config), prompt_overhead_chars=overhead)


@pytest.mark.parametrize(
    "config",
    [
        {"fallback": "whole_document"},
        {"strategy": "semantic", "chunk_chars": 2000, "overlap_chars": 2000},
    ],
)
def test_ineffective_chunking_rejected(config):
    with pytest.raises(ValidationError):
        ChunkingConfig(**config)


def test_sheet_strategy_rejects_pdf_instead_of_pretending_to_split_worksheets():
    with pytest.raises(ContextLimitExceeded):
        plan_chunks(["text"], ChunkingConfig(strategy="sheet"), unit_kind="page")


def test_shared_extraction_reuses_preserved_text_between_segments(monkeypatch):
    submitted = []

    def invoke(call):
        submitted.append(call.user)
        return StructuredResult(
            parsed=ExtractionOut(fields=[]), raw_response="{}", model_deployment="fixture"
        )

    ctx = context("custom", invoke)
    doc = layout()
    doc.units.append(doc.units[0].model_copy(update={"index": 1, "number": 2}))
    texts = ["=== PAGE 1 (unit 0) ===\nFirst note", "=== PAGE 2 (unit 1) ===\nSecond note"]
    monkeypatch.setattr(
        "docai.workflows.extraction_core.preserve", lambda *_: pytest.fail("Rebuilt text")
    )
    for index in range(2):
        result = run_extraction(
            ctx,
            doc,
            ctx.config.schema_,
            document_type="note",
            unit_range=(index, index),
            segment_index=index,
            unit_texts=texts,
        )
        assert all(field.segment_index == index for field in result.fields)
    assert "Second note" not in submitted[0]
    assert "First note" not in submitted[1]


@pytest.mark.parametrize("mode", ["custom", "default"])
def test_full_prompt_budget_rejects_large_instructions_without_calling_llm(mode):
    ctx = context(mode, lambda _: pytest.fail("Provider must not be called"))
    ctx.config.chunking.max_request_chars = 2000
    stage = "extraction" if mode == "custom" else "generic_kv"
    ctx.prompts[stage].system = "instructions " * 1000
    with pytest.raises(ContextLimitExceeded):
        ExtractStructured().process_document(ctx, layout())


@pytest.mark.parametrize(
    "policy", ["highest_score", "first_non_null", "majority", "conflicts_to_review"]
)
def test_distinct_list_outputs_retain_chunk_and_segment_identity_and_require_review(policy):
    def invoke(call):
        value = json.dumps([{"state": "NY", "amount": 100 if call.chunk_index == 0 else 200}])
        return StructuredResult(
            parsed=ExtractionOut.model_validate(
                {"fields": [{"name": "valid", "value": value, "confidence": 1}]}
            ),
            raw_response="{}",
            model_deployment="fixture",
        )

    ctx = context("custom", invoke)
    ctx.config.schema_.fields[0].type = "list"
    ctx.config.chunking.strategy = "page"
    doc = layout()
    doc.units.append(doc.units[0].model_copy(update={"index": 1, "number": 2}))
    result = run_extraction(
        ctx,
        doc,
        ctx.config.schema_,
        document_type="note",
        segment_index=4,
        reconciliation_policy=policy,
    )
    field = result.fields[0]
    assert field.conflict and field.review_outcome == "human_review"
    assert [candidate["chunk_index"] for candidate in field.candidates] == [0, 1]
    assert all(candidate["segment_index"] == 4 for candidate in field.candidates)
    assert len({candidate["value"] for candidate in field.candidates}) == 2
