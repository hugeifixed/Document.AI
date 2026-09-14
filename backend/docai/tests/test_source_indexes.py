"""Original page identity survives blank exclusion, chunking, grounding and persistence."""

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from docai import input_quality
from docai.adapters.llm.mock import MockStructuredLLM
from docai.input_quality import PreparedInput
from docai.schemas.layout import LayoutDocument, LayoutPage, Span, Word
from docai.schemas.llm import ClassificationOut, FieldOut, SourceRef, StructuredResult
from docai.services import governance, ingestion, layouts, run_execution, runs
from docai.synthetic.pdfwriter import write_pdf

pytestmark = pytest.mark.django_db


@pytest.fixture
def source_document(dataset, admin, monkeypatch):
    document = ingestion.ingest_upload(
        dataset,
        "repeated.pdf",
        write_pdf([["Cover"], [], ["Invoice Total: 100.00"], ["Invoice Total: 100.00"]]),
        user=admin,
    )
    pages = [
        LayoutPage(
            index=index,
            number=index + 1,
            content="Cover" if index == 0 else "Invoice\nTotal: 100.00",
            words=[]
            if index == 0
            else [
                Word(
                    id=f"p{index + 1}:w0",
                    text="100.00",
                    span=Span(offset=15, length=6),
                    polygon=[0.1, 0.1, 0.3, 0.1, 0.3, 0.2, 0.1, 0.2],
                )
            ],
        )
        for index in (0, 2, 3)
    ]

    @contextmanager
    def prepare(path, **kwargs):
        yield PreparedInput(
            path,
            "pdf",
            selected_pages="1,3-4",
            summary={"mode": "adaptive", "status": "applied"},
            page_details=[
                {
                    "page": index + 1,
                    "status": "skipped" if index == 1 else "unchanged",
                    "has_text_layer": False,
                }
                for index in range(4)
            ],
        )

    def analyze(path, **kwargs):
        assert kwargs["pages"] == "1,3-4"
        return LayoutDocument(
            document_id=str(document.pk), source_format="pdf", service="fixture", units=pages
        )

    monkeypatch.setattr(input_quality, "prepare_input", prepare)
    monkeypatch.setattr(
        layouts,
        "get_layout_provider_for_format",
        lambda *_, **kwargs: SimpleNamespace(key="fixture", supports_ocr=True, analyze=analyze),
    )
    return document


def workflow_config(kind, strategy):
    schema = {"name": "totals", "fields": [{"name": "total", "type": "currency"}]}
    config: dict[str, Any] = {"chunking": {"strategy": strategy}}
    if kind.startswith("classify"):
        config["categories"] = [{"key": "invoice", "name": "Invoice"}]
        if kind == "classify_structured":
            config.update(
                rules=[
                    {
                        "category": "invoice",
                        "required": [{"kind": "phrase", "pattern": "Missing title"}],
                    }
                ],
                use_llm_fallback=True,
            )
    elif kind == "unbundle_classify_extract":
        config.update(
            categories=[{"key": "invoice", "name": "Invoice", "extraction_schema": "totals"}],
            schemas=[schema],
        )
    elif kind == "generic":
        config["mode"] = "default"
    else:
        config["schema"] = schema
    return config


@pytest.mark.parametrize("strategy", ["whole_document", "page", "context_length", "semantic"])
@pytest.mark.parametrize(
    "kind",
    [
        "classify_unstructured",
        "classify_structured",
        "generic",
        "extract_structured",
        "extract_unstructured",
        "unbundle_classify_extract",
    ],
)
def test_original_citations_persist_on_page_three_not_repeated_page_four(
    source_document, project, admin, monkeypatch, kind, strategy
):
    config = workflow_config(kind, strategy)
    workflow = governance.create_workflow_version(
        project,
        "original-indexes",
        "extract_structured" if kind == "generic" else kind,
        config,
        admin,
    )
    calls = []

    def invoke(self, call):
        calls.append(call)
        assert "ORIGINAL" in call.system and "Never renumber" in call.system
        data: dict[str, Any]
        if call.stage == "segmentation":
            assert "[1]" not in call.user
            data = {
                "segments": [
                    {"start_unit": 0, "end_unit": 1, "category": "other"},
                    {
                        "start_unit": 2,
                        "end_unit": 3,
                        "category": "invoice",
                        "confidence": 0.99,
                        "sources": [{"unit_index": 2, "ids": ["p3:w0"]}],
                    },
                ]
            }
        else:
            assert "PAGE 2" not in call.user
            target = "PAGE 3" in call.user
            source = {"unit_index": 2, "ids": ["p3:w0"], "quote": "100.00"}
            field = {
                "name": "total",
                "value": "100.00" if target else None,
                "confidence": 0.99 if target else 0,
                "unit_index": 2 if target else None,
                "sources": [source] if target else [],
            }
            if call.stage == "classification":
                data = {
                    "category": "invoice",
                    "confidence": 0.99 if target else 0,
                    "sources": [source] if target else [],
                }
            else:
                data = {
                    "pairs" if call.stage == "generic_kv" else "fields": [field]
                    if target or call.stage != "generic_kv"
                    else []
                }
        return StructuredResult(
            parsed=call.schema.model_validate(data), raw_response="{}", model_deployment="offline"
        )

    monkeypatch.setattr(MockStructuredLLM, "invoke", invoke)
    run = run_execution.execute_run(
        runs.create_run(project, workflow, source_document.dataset, admin).pk
    )
    assert run.status == "succeeded"
    artifact = run.items.get().layout_artifact
    assert artifact is not None
    assert list(artifact.units.order_by("index").values_list("index", flat=True)) == [0, 1, 2, 3]
    if kind.startswith("classify"):
        span = run.classifications.get().spans.get()
    else:
        field = run.fields.get(name="total")
        assert field.raw_value == "100.00" and field.grounded
        span = field.spans.get()
        if kind == "unbundle_classify_extract":
            assert field.segment is not None
            assert field.segment.start_unit == 2
            assert field.segment.spans.get().unit.index == 2
            assert run.classifications.get(segment=field.segment).spans.get().word_ids == ["p3:w0"]
    assert span.unit.index == 2 and span.word_ids == ["p3:w0"]
    assert span.unit.layout_artifact_id == artifact.pk
    assert calls


@pytest.mark.parametrize(
    "invalid_source",
    [
        {"unit_index": 99, "ids": ["p3:w0"]},
        {"unit_index": 1, "ids": []},
        {"unit_index": 3, "ids": ["p3:w0"]},
        {"unit_index": 2, "ids": ["p3:unknown"]},
    ],
)
@pytest.mark.parametrize("kind", ["classify_unstructured", "generic", "extract_unstructured"])
def test_invalid_citations_never_create_misleading_persisted_evidence(
    source_document, project, admin, monkeypatch, kind, invalid_source
):
    workflow = governance.create_workflow_version(
        project,
        "invalid-index",
        "extract_structured" if kind == "generic" else kind,
        workflow_config(kind, "whole_document"),
        admin,
    )

    def invoke(self, call):
        field = {"name": "total", "value": "100.00", "sources": [invalid_source]}
        data = (
            {"category": "invoice", "sources": [invalid_source]}
            if call.schema is ClassificationOut
            else {"pairs" if kind == "generic" else "fields": [field]}
        )
        return StructuredResult(
            parsed=call.schema.model_validate(data), raw_response="{}", model_deployment="offline"
        )

    monkeypatch.setattr(MockStructuredLLM, "invoke", invoke)
    run = run_execution.execute_run(
        runs.create_run(project, workflow, source_document.dataset, admin).pk
    )
    assert not any(field.grounded or field.spans.exists() for field in run.fields.all())
    assert not any(row.spans.exists() for row in run.classifications.all())
    assert all(row.review_status == "needs_review" for row in run.classifications.all())


@pytest.mark.parametrize(
    "kind",
    ["classify_unstructured", "generic", "extract_unstructured", "unbundle_classify_extract"],
)
@pytest.mark.parametrize("strategy", ["whole_document", "page"])
def test_mock_obeys_original_indexes_after_blank_skipping(
    source_document, project, admin, kind, strategy
):
    workflow = governance.create_workflow_version(
        project,
        "mock-index",
        "extract_structured" if kind == "generic" else kind,
        workflow_config(kind, strategy),
        admin,
    )
    run = run_execution.execute_run(
        runs.create_run(project, workflow, source_document.dataset, admin).pk
    )
    assert run.status == "succeeded"
    if kind == "classify_unstructured":
        assert run.classifications.get().spans.get().unit.index == 2
    elif kind == "unbundle_classify_extract":
        fields = list(run.fields.order_by("segment__start_unit"))
        assert [field.spans.get().unit.index for field in fields] == [2, 3]
        assert all(field.grounded for field in fields)
    else:
        field = run.fields.get(name__iexact="total")
        assert field.grounded and field.spans.get().unit.index == 2


def test_explicit_word_citation_selects_matching_occurrence_and_rejects_inconsistent_hint():
    from docai.workflows.extraction_core import ground

    page = LayoutPage(
        index=2,
        number=3,
        content="100.00 100.00",
        words=[Word(id="p3:w0", text="100.00"), Word(id="p3:w1", text="100.00")],
    )
    layout = LayoutDocument(
        document_id="repeated", source_format="pdf", service="fixture", units=[page]
    )
    field = FieldOut(name="total", value="100.00", sources=[SourceRef(unit_index=2, ids=["p3:w1"])])
    hit = ground(layout, field, 2)
    assert hit is not None and hit["word_ids"] == ["p3:w1"]
    assert ground(layout, field, 0) is None
    assert ground(layout, field, 2, allowed_indexes={0, 1}) is None


@pytest.mark.parametrize("strategy", ["context_length", "semantic"])
def test_overlap_citations_remain_original_when_the_next_chunk_starts_on_another_page(
    source_document, project, admin, monkeypatch, strategy
):
    # The first body fills a chunk. Its Total line then appears only as overlap
    # in the next chunk, whose primary page is original page 4.
    document = source_document
    provider = layouts.get_layout_provider_for_format("pdf")
    original_analyze = provider.analyze

    def analyze(*args, **kwargs):
        layout = original_analyze(*args, **kwargs)
        layout.pages[1].content = "Invoice\n" + ("Context " * 240) + "\nTotal: 100.00"
        layout.pages[2].content = "Following page " * 120
        return layout

    monkeypatch.setattr(provider, "analyze", analyze)
    monkeypatch.setattr(layouts, "get_layout_provider_for_format", lambda *_, **kwargs: provider)
    config = workflow_config("extract_unstructured", strategy)
    config["chunking"].update(chunk_chars=2000, overlap_chars=80)
    workflow = governance.create_workflow_version(
        project, "overlap", "extract_unstructured", config, admin
    )
    cited_overlap = []

    def invoke(self, call):
        overlap = "Following page" in call.user and "Total: 100.00" in call.user
        if overlap:
            assert "PAGE 3 (unit 2)" in call.user
            assert 2 in call.mock_context["unit_indexes"]
            cited_overlap.append(call)
        field = FieldOut(
            name="total",
            value="100.00" if overlap else None,
            confidence=0.99 if overlap else 0,
            sources=[SourceRef(unit_index=2, ids=["p3:w0"])] if overlap else [],
        )
        return StructuredResult(
            parsed=call.schema.model_validate({"fields": [field]}),
            raw_response="{}",
            model_deployment="offline",
        )

    monkeypatch.setattr(MockStructuredLLM, "invoke", invoke)
    run = run_execution.execute_run(runs.create_run(project, workflow, document.dataset, admin).pk)
    assert cited_overlap
    assert run.fields.get(name="total").spans.get().unit.index == 2


@pytest.mark.parametrize("kind", ["line", "table", "sheet"])
def test_cited_layout_element_bounds_repeated_value_grounding(kind):
    from docai.schemas.layout import LayoutSheet, Line, SheetCell, Table, TableCell
    from docai.workflows.extraction_core import ground

    unit: LayoutPage | LayoutSheet
    if kind == "sheet":
        unit = LayoutSheet(
            index=2,
            name="Totals",
            row_count=2,
            col_count=1,
            cells=[
                SheetCell(id=f"s2:A{i}", ref=f"A{i}", row=i - 1, col=0, value="100.00")
                for i in (1, 2)
            ],
        )
        citation, expected = "s2:A2", "s2:A2"
    else:
        unit = LayoutPage(
            index=2,
            number=3,
            content="100.00 100.00",
            words=[
                Word(id=f"p3:w{i}", text="100.00", span=Span(offset=i * 7, length=6))
                for i in (0, 1)
            ],
        )
        if kind == "line":
            unit.lines = [Line(id="p3:l1", text="100.00", word_ids=["p3:w1"])]
            citation = "p3:l1"
        else:
            unit.tables = [
                Table(
                    id="p3:t0",
                    row_count=1,
                    col_count=1,
                    cells=[
                        TableCell(
                            id="p3:t0:r0:c0",
                            row=0,
                            col=0,
                            text="100.00",
                            span=Span(offset=7, length=6),
                        )
                    ],
                )
            ]
            citation = "p3:t0"
        expected = "p3:w1"
    layout = LayoutDocument(
        document_id="repeated",
        source_format="xlsx" if kind == "sheet" else "pdf",
        service="fixture",
        units=[unit],
    )
    field = FieldOut(
        name="total", value="100.00", sources=[SourceRef(unit_index=2, ids=[citation])]
    )
    hit = ground(layout, field, 2)
    assert hit is not None and hit["word_ids"] == [expected]
