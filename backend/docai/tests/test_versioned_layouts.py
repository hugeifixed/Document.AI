"""Representation isolation across execution, review, retry and database migration.

Native image behavior lives in processor tests. These tests exercise the service
boundary using bounded synthetic inputs and an offline layout-provider double.
"""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from docai.adapters.storage import read_bytes, save_bytes
from docai.exceptions import IntegrationError, NormalizationUnavailable, SpanMappingFailed
from docai.input_quality import PreparedInput
from docai.layout.chunk import plan_chunks
from docai.layout.preserve import preserve
from docai.models import Document, GroundTruthLabel, RunItem, SourceSpan
from docai.schemas.config import ChunkingConfig, DIAnalysisConfig, InputQualityConfig
from docai.schemas.layout import LayoutDocument, LayoutPage, Span, Word
from docai.services import labeling, layouts, run_execution, runs

pytestmark = pytest.mark.django_db


@pytest.fixture
def document(dataset, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    storage_path, digest = save_bytes(f"tests/{uuid4().hex}.pdf", b"%PDF synthetic original")
    return Document.objects.create(
        dataset=dataset,
        original_filename="scanned-form.pdf",
        file_format="pdf",
        mime_type="application/pdf",
        sha256=digest,
        size_bytes=23,
        storage_path=storage_path,
        page_count=1,
        status="validated",
    )


@pytest.fixture
def provider(monkeypatch):
    calls = []

    def analyze(path, *, document_id, source_format, **options):
        calls.append((path.read_bytes(), options))
        return LayoutDocument(
            document_id=document_id,
            source_format=source_format,
            service="fixture",
            units=[
                LayoutPage(
                    index=0,
                    number=1,
                    content="Total 100",
                    width=100,
                    height=100,
                    unit="point",
                    words=[
                        Word(
                            id="p1:w0",
                            text="100",
                            span=Span(offset=6, length=3),
                            polygon=[0.1, 0.1, 0.3, 0.1, 0.3, 0.2, 0.1, 0.2],
                        )
                    ],
                )
            ],
        )

    monkeypatch.setattr(
        layouts,
        "get_layout_provider_for_format",
        lambda *_, **kwargs: SimpleNamespace(
            key="fixture",
            supports_ocr=True,
            analyze=analyze,
        ),
    )
    return calls


def make_run(sample_workflow, document, admin):
    return runs.create_run(document.dataset.project, sample_workflow, document.dataset, admin)


def adaptive(monkeypatch, tmp_path, *, status="applied", details=None):
    import docai.input_quality as quality_module

    path = tmp_path / f"{uuid4().hex}.pdf"
    path.write_bytes(b"%PDF transformed source")
    summary = {
        "mode": "adaptive",
        "status": status,
        "profile": "adaptive-v1",
        "pages_examined": 1,
        "pages_adjusted": 1 if status == "applied" else 0,
        "pages_skipped": 0,
        "duration_ms": 12,
        "warnings": []
        if status == "applied"
        else [
            {
                "code": "NORMALIZATION_FALLBACK",
                "message": "Original used safely.",
                "pages": [1],
                "retryable": False,
            }
        ],
    }

    @contextmanager
    def prepare(original, **kwargs):
        yield PreparedInput(
            path if status == "applied" else original,
            "pdf",
            summary=summary,
            page_details=details
            or [
                {
                    "page": 1,
                    "status": "adjusted",
                    "width": 100,
                    "height": 100,
                    "unit": "point",
                    "has_text_layer": False,
                }
            ],
        )

    monkeypatch.setattr(quality_module, "prepare_input", prepare)
    monkeypatch.setattr(quality_module, "validate_input_quality", lambda *_: None)
    return InputQualityConfig(mode="adaptive")


def test_layout_cache_is_scalar_policy_scoped_and_preserves_historical_evidence(
    document,
    provider,
    sample_workflow,
    admin,
):
    run = make_run(sample_workflow, document, admin)
    item = run.items.get()
    layouts.get_or_build_layout(document, run_item=item)
    first_artifact = item.layout_artifact
    first_unit = first_artifact.units.get()
    label = labeling.label_from_word_ids(
        document,
        run=run.pk,
        unit_index=0,
        field_name="total",
        expected_value="100",
        word_ids=["p1:w0"],
        user=admin,
    )
    milestones = []
    with CaptureQueriesContext(connection) as queries:
        layouts.get_or_build_layout(document, milestone=lambda *args: milestones.append(args))
    assert len(provider) == 1
    assert milestones == [("reading_document", "reusing_layout")]
    assert any("cache_key" in query["sql"] for query in queries)
    assert not any("JSON_EXTRACT" in query["sql"] for query in queries)
    layouts.get_or_build_layout(
        document, "azure_di", di_analysis=DIAnalysisConfig(ocr_high_resolution=True)
    )
    assert len(provider) == 2
    assert provider[-1][1] == {"ocr_high_resolution": True}
    assert document.units.count() == 2
    label.refresh_from_db()
    assert label.unit_id == first_unit.pk
    assert SourceSpan.objects.get(label=label).unit_id == first_unit.pk
    selected = layouts.artifact_for_document(document, run.pk)
    assert selected is not None and selected.pk == first_artifact.pk
    assert read_bytes(first_artifact.storage_path)
    assert len(set(document.artifacts.values_list("storage_path", flat=True))) == 2


def test_processor_revision_invalidates_adaptive_cache_without_replacing_historical_sources(
    document, provider, sample_workflow, admin, monkeypatch, tmp_path
):
    from docai import input_quality

    quality = adaptive(monkeypatch, tmp_path)
    old_run = make_run(sample_workflow, document, admin)
    old_item = old_run.items.get()
    monkeypatch.setattr(input_quality, "PROCESSOR_REVISION", 1, raising=False)
    layouts.get_or_build_layout(document, input_quality=quality, run_item=old_item)
    old_artifact = old_item.layout_artifact
    old_source = read_bytes(old_artifact.source_artifact.storage_path)
    off_key = layouts._policy_key(document, "fixture", InputQualityConfig(), DIAnalysisConfig())

    monkeypatch.setattr(input_quality, "PROCESSOR_REVISION", 2)
    new_run = make_run(sample_workflow, document, admin)
    new_item = new_run.items.get()
    layouts.get_or_build_layout(document, input_quality=quality, run_item=new_item)
    assert len(provider) == 2
    assert new_item.layout_artifact_id != old_artifact.pk
    historical = layouts.artifact_for_document(document, old_run.pk)
    assert historical is not None and historical.pk == old_artifact.pk
    assert read_bytes(old_artifact.source_artifact.storage_path) == old_source
    assert (
        layouts._policy_key(document, "fixture", InputQualityConfig(), DIAnalysisConfig())
        == off_key
    )
    layouts.get_or_build_layout(document, input_quality=quality)
    assert len(provider) == 2  # The current revision still reuses its completed layout.


def test_derived_processing_source_is_private_exact_and_readable_after_disabling(
    api,
    document,
    provider,
    sample_workflow,
    admin,
    viewer,
    monkeypatch,
    tmp_path,
    settings,
):
    original_run = make_run(sample_workflow, document, admin)
    original_item = original_run.items.get()
    layouts.get_or_build_layout(document, run_item=original_item)
    derived_run = make_run(sample_workflow, document, admin)
    derived_item = derived_run.items.get()
    quality = adaptive(monkeypatch, tmp_path)
    layouts.get_or_build_layout(document, input_quality=quality, run_item=derived_item)
    settings.DOCAI_IMAGE_NORMALIZATION_ENABLED = False
    response = api.get(f"/api/v1/documents/{document.pk}/?run={derived_run.pk}")
    assert response.status_code == 200
    detail = response.json()["data"]
    assert len(detail["units"]) == 1
    assert detail["processing_source"]["is_original"] is False
    assert detail["processing_source"]["layout_artifact"] == str(derived_item.layout_artifact_id)
    response = api.get(detail["processing_source"]["url"])
    assert b"".join(response.streaming_content) == b"%PDF transformed source"
    assert "private" in response["Cache-Control"]
    response = api.get(f"/api/v1/documents/{document.pk}/processing-source/?run={original_run.pk}")
    assert b"".join(response.streaming_content) == b"%PDF synthetic original"
    denied = APIClient()
    denied.force_authenticate(viewer)
    assert denied.get(detail["processing_source"]["url"]).status_code == 403
    assert (
        denied.get(f"/api/v1/documents/{document.pk}/units/0/?run={derived_run.pk}").status_code
        == 403
    )
    unit = api.get(f"/api/v1/documents/{document.pk}/units/0/?run={derived_run.pk}").json()["data"]
    assert unit["has_text_layer"] is False
    assert unit["content"] == "Total 100"


def test_pending_or_unrelated_run_never_falls_back_to_another_layout(
    api,
    document,
    provider,
    sample_workflow,
    admin,
):
    layouts.get_or_build_layout(document)
    pending = make_run(sample_workflow, document, admin)
    detail = api.get(f"/api/v1/documents/{document.pk}/?run={pending.pk}").json()["data"]
    assert detail["units"] == []
    assert detail["processing_source"]["layout_artifact"] is None
    assert detail["processing_source"]["is_original"] is True
    assert api.get(f"/api/v1/documents/{document.pk}/units/0/?run={pending.pk}").status_code == 404
    for suffix in ("", "units/0/", "processing-source/"):
        assert api.get(f"/api/v1/documents/{document.pk}/{suffix}?run={uuid4()}").status_code == 404
        assert api.get(f"/api/v1/documents/{document.pk}/{suffix}?run=bad").status_code == 404


def test_labels_keep_run_specific_geometry_and_cross_run_values(
    api,
    document,
    provider,
    sample_workflow,
    admin,
    monkeypatch,
    tmp_path,
):
    first_run = make_run(sample_workflow, document, admin)
    layouts.get_or_build_layout(document, run_item=first_run.items.get())
    capture = {
        "document": str(document.pk),
        "mode": "word_ids",
        "field_name": "total",
        "unit_index": 0,
        "expected_value": "100",
        "word_ids": ["p1:w0"],
    }
    first = api.post("/api/v1/labels/", {**capture, "run": str(first_run.pk)}, format="json")
    assert first.status_code == 201
    second_run = make_run(sample_workflow, document, admin)
    layouts.get_or_build_layout(
        document, input_quality=adaptive(monkeypatch, tmp_path), run_item=second_run.items.get()
    )
    second = api.post(
        "/api/v1/labels/",
        {**capture, "expected_value": "101", "run": str(second_run.pk)},
        format="json",
    )
    assert second.status_code == 201
    for run, label_response in ((first_run, first), (second_run, second)):
        response = api.get(f"/api/v1/labels/?document={document.pk}&run={run.pk}")
        assert [x["id"] for x in response.json()["data"]["results"]] == [
            label_response.json()["data"]["id"]
        ]
    from docai.services.evaluation import _labels

    assert _labels(first_run)[0].expected_value == "101"
    assert _labels(second_run)[0].expected_value == "101"
    bad = api.post("/api/v1/labels/", {**capture, "run": str(uuid4())}, format="json")
    assert bad.status_code == 404
    with pytest.raises(SpanMappingFailed, match="OCR word selection"):
        labeling.label_from_pdfjs(
            document,
            run=second_run.pk,
            unit_index=0,
            field_name="total",
            expected_value="101",
            text="100",
            rects=[],
            page_width_pt=100,
            page_height_pt=100,
            user=admin,
        )


def test_normalization_fallback_is_visible_success_and_not_reused_as_adaptive_cache(
    document,
    provider,
    sample_workflow,
    admin,
    monkeypatch,
    tmp_path,
):
    quality = adaptive(monkeypatch, tmp_path, status="fallback")
    run = make_run(sample_workflow, document, admin)
    item = run.items.get()
    layouts.get_or_build_layout(document, input_quality=quality, run_item=item)
    first_id = item.layout_artifact_id
    assert item.input_quality["warnings"][0]["code"] == "NORMALIZATION_FALLBACK"
    assert not item.error_code
    assert not item.layout_artifact.cache_key
    assert item.layout_artifact.source_artifact_id is None
    layouts.get_or_build_layout(document, input_quality=quality, run_item=item)
    assert len(provider) == 2
    assert item.layout_artifact_id != first_id


@pytest.mark.parametrize("strategy", ["page", "whole_document", "context_length", "semantic"])
def test_blank_exclusion_keeps_original_indexes_in_every_chunk_strategy(strategy):
    layout = LayoutDocument(
        document_id="test",
        source_format="pdf",
        service="fixture",
        units=[
            LayoutPage(index=0, number=1, content="A"),
            LayoutPage(index=1, number=2, excluded_from_analysis=True),
            LayoutPage(index=2, number=3, content="C"),
        ],
    )
    plan = plan_chunks(
        preserve(layout), ChunkingConfig(strategy=strategy), excluded_unit_indexes={1}
    )
    assert {index for chunk in plan.chunks for index in chunk.unit_indexes} == {0, 2}
    assert all("PAGE 2" not in chunk.text for chunk in plan.chunks)
    assert "PAGE 3" in plan.chunks[-1].text
    assert not plan_chunks(
        [""], ChunkingConfig(strategy=strategy), excluded_unit_indexes={0}
    ).chunks


def test_selected_blank_page_placeholder_does_not_renumber_azure_pages():
    layout = LayoutDocument(
        document_id="test",
        source_format="pdf",
        service="fixture",
        units=[
            LayoutPage(index=0, number=1, content="A"),
            LayoutPage(index=2, number=3, content="C"),
        ],
    )
    details = [
        {
            "page": i,
            "status": "skipped" if i == 2 else "unchanged",
            "has_text_layer": False,
            "width": 100,
            "height": 100,
            "unit": "point",
        }
        for i in (1, 2, 3)
    ]
    layouts._complete_pages(layout, details)
    assert [unit.index for unit in layout.units] == [0, 1, 2]
    assert layout.pages[1].excluded_from_analysis
    assert not layout.pages[2].has_text_layer
    layout.units = [layout.pages[0]]
    with pytest.raises(IntegrationError) as raised:
        layouts._complete_pages(layout, details)
    assert raised.value.error_code == "INCOMPLETE_LAYOUT"
    assert "2 of 3 expected pages" in str(raised.value)
    assert raised.value.retryable is False


def test_gate_is_checked_before_run_creation_and_again_by_worker(
    document,
    sample_workflow,
    admin,
    settings,
):
    sample_workflow.config["input_quality"] = {"mode": "adaptive"}
    settings.DOCAI_IMAGE_NORMALIZATION_ENABLED = False
    with pytest.raises(NormalizationUnavailable):
        make_run(sample_workflow, document, admin)
    assert not document.run_items.exists()
    sample_workflow.config["input_quality"] = {"mode": "off"}
    run = make_run(sample_workflow, document, admin)
    run.config_snapshot["config"]["input_quality"]["mode"] = "adaptive"
    run.save(update_fields=["config_snapshot"])
    item = run.items.get()
    assert run_execution.process_item(item.pk) == "failed"
    item.refresh_from_db()
    assert item.error_code == "NORMALIZATION_UNAVAILABLE"
    assert item.stage == "normalization"
    assert not item.layout_artifact_id


def test_cancellation_before_analysis_preserves_original_and_creates_no_artifact(
    document,
    provider,
    sample_workflow,
    admin,
    monkeypatch,
):
    run = make_run(sample_workflow, document, admin)
    original_claim = run_execution._claim_item

    def claim(*args):
        item, claimed = original_claim(*args)
        type(run).objects.filter(pk=run.pk).update(cancel_requested=True)
        return item, claimed

    monkeypatch.setattr(run_execution, "_claim_item", claim)
    item = run.items.get()
    assert run_execution.process_item(item.pk) == "skipped"
    assert not provider
    assert not document.artifacts.exists()
    assert read_bytes(document.storage_path) == b"%PDF synthetic original"


def test_backfill_links_only_identifiable_layout_and_preserves_spans(
    document,
    provider,
    sample_workflow,
    admin,
):
    run = make_run(sample_workflow, document, admin)
    item = run.items.get()
    layouts.get_or_build_layout(document, run_item=item)
    artifact = item.layout_artifact
    label = labeling.label_from_word_ids(
        document,
        unit_index=0,
        field_name="total",
        expected_value="100",
        word_ids=["p1:w0"],
        user=admin,
    )
    RunItem.objects.filter(pk=item.pk).update(
        layout_artifact=None, status="succeeded", stage="done"
    )
    queued = make_run(sample_workflow, document, admin).items.get()
    migration = importlib.import_module("docai.migrations.0007_version_processing_layouts")
    migration.backfill_run_layouts(apps, SimpleNamespace(connection=connection))
    item.refresh_from_db()
    assert item.layout_artifact_id == artifact.pk
    queued.refresh_from_db()
    assert queued.layout_artifact_id is None
    assert SourceSpan.objects.filter(label=label).exists()
    layouts.get_or_build_layout(
        document, "azure_di", di_analysis=DIAnalysisConfig(ocr_high_resolution=True)
    )
    item.save()  # both versions now predate the unidentifiable historical item
    RunItem.objects.filter(pk=item.pk).update(layout_artifact=None)
    migration.backfill_run_layouts(apps, SimpleNamespace(connection=connection))
    item.refresh_from_db()
    assert item.layout_artifact_id is None
    assert GroundTruthLabel.objects.get(pk=label.pk).unit_id is not None


def test_worker_result_spans_bind_to_its_layout_even_when_a_newer_one_exists(
    document,
    provider,
    sample_workflow,
    admin,
    monkeypatch,
):
    from docai.workflows.base import ClassificationResultData, DocumentResult

    run = make_run(sample_workflow, document, admin)
    item = run.items.get()
    layouts.get_or_build_layout(document, run_item=item)
    expected_artifact = item.layout_artifact_id
    layouts.get_or_build_layout(
        document, "azure_di", di_analysis=DIAnalysisConfig(ocr_high_resolution=True)
    )
    result = DocumentResult(
        classifications=[
            ClassificationResultData(
                category="invoice",
                score=0.99,
                method="llm",
                sources=[{"unit_index": 0, "quote": "100", "ids": ["p1:w0"]}],
            )
        ]
    )
    monkeypatch.setattr(
        run_execution,
        "get_strategy",
        lambda _: SimpleNamespace(
            process_document=lambda *_: result,
        ),
    )
    assert run_execution.process_item(item.pk) == "succeeded"
    item.refresh_from_db()
    assert item.layout_artifact_id == expected_artifact
    assert item.input_quality["status"] == "off"
    assert not item.error_code
    assert (
        SourceSpan.objects.get(classification__run=run).unit.layout_artifact_id == expected_artifact
    )


def test_historical_versions_do_not_duplicate_document_search_or_prevent_document_deletion(
    api,
    document,
    provider,
    sample_workflow,
    admin,
):
    run = make_run(sample_workflow, document, admin)
    layouts.get_or_build_layout(document, run_item=run.items.get())
    layouts.get_or_build_layout(
        document, "azure_di", di_analysis=DIAnalysisConfig(ocr_high_resolution=True)
    )
    response = api.get(f"/api/v1/documents/?dataset={document.dataset_id}&search=Total")
    assert response.status_code == 200
    assert response.json()["data"]["count"] == 1
    assert len(response.json()["data"]["results"]) == 1
    first_unit = run.items.get().layout_artifact.units.get()
    first_unit.text_preview = "obsolete-OCR-only"
    first_unit.save(update_fields=["text_preview"])
    assert (
        api.get(
            f"/api/v1/documents/?search=obsolete-OCR-only&dataset={document.dataset_id}"
        ).json()["data"]["count"]
        == 0
    )
    assert api.delete(f"/api/v1/documents/{document.pk}/").status_code == 204


def test_invalid_label_run_document_selector_returns_not_found(
    api,
    document,
    sample_workflow,
    admin,
):
    run = make_run(sample_workflow, document, admin)
    assert api.get(f"/api/v1/labels/?run={run.pk}&document=bad").status_code == 404
    assert api.get(f"/api/v1/labels/?run=bad&document={document.pk}").status_code == 404


def test_unpublished_files_are_cleaned_up_when_database_publication_fails(
    document,
    provider,
    monkeypatch,
    tmp_path,
    settings,
):
    quality = adaptive(monkeypatch, tmp_path)
    original_files = set(settings.MEDIA_ROOT.rglob("*"))

    def fail(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(layouts.SourceUnit.objects, "bulk_create", fail)
    with pytest.raises(RuntimeError, match="database unavailable"):
        layouts.get_or_build_layout(document, input_quality=quality)
    assert not document.artifacts.exists()
    assert {path for path in settings.MEDIA_ROOT.rglob("*") if path.is_file()} == {
        path for path in original_files if path.is_file()
    }


def test_high_resolution_policy_requires_azure_at_creation_and_execution(
    document,
    sample_workflow,
    admin,
):
    from docai.exceptions import WorkflowConfigError

    sample_workflow.config["di_analysis"] = {"ocr_high_resolution": True}
    with pytest.raises(WorkflowConfigError) as raised:
        make_run(sample_workflow, document, admin)
    assert "di_analysis.ocr_high_resolution" in raised.value.errors
    assert not document.run_items.exists()
    sample_workflow.config["di_analysis"] = {"ocr_high_resolution": False}
    run = make_run(sample_workflow, document, admin)
    run.config_snapshot["config"]["di_analysis"]["ocr_high_resolution"] = True
    run.save(update_fields=["config_snapshot"])
    item = run.items.get()
    assert run_execution.process_item(item.pk) == "failed"
    item.refresh_from_db()
    assert item.error_code == "WORKFLOW_CONFIG_ERROR"


@pytest.mark.parametrize("promotion", [False, True])
def test_present_absent_transitions_supersede_truth_across_representations(
    api, document, provider, sample_workflow, admin, monkeypatch, tmp_path, promotion
):
    from docai.models import ExtractedField
    from docai.services import review
    from docai.services.evaluation import _labels

    first_run = make_run(sample_workflow, document, admin)
    first_item = first_run.items.get()
    layouts.get_or_build_layout(document, run_item=first_item)
    first = labeling.label_from_word_ids(
        document,
        run=first_run.pk,
        unit_index=0,
        field_name="total",
        expected_value="100",
        word_ids=["p1:w0"],
        user=admin,
    )
    first_span = SourceSpan.objects.get(label=first)
    second_run = make_run(sample_workflow, document, admin)
    second_item = second_run.items.get()
    layouts.get_or_build_layout(
        document, input_quality=adaptive(monkeypatch, tmp_path), run_item=second_item
    )
    second = labeling.label_from_word_ids(
        document,
        run=second_run.pk,
        unit_index=0,
        field_name="total",
        expected_value="101",
        word_ids=["p1:w0"],
        user=admin,
    )
    field = ExtractedField.objects.create(
        run=second_run,
        document=document,
        name="total",
        raw_value="101",
        review_status="corrected",
        reviewed_value="101",
    )
    SourceSpan.objects.create(
        field=field, unit=second_item.layout_artifact.units.get(), word_ids=["p1:w0"]
    )
    if promotion:
        # Promotion on another representation preserves the old representation's geometry.
        second = labeling.promote_field_to_ground_truth(field, admin)
        first.refresh_from_db()
        assert first.status == "final"
        review.act_on_field(field, "mark_absent", admin)
        absent = labeling.promote_field_to_ground_truth(field, admin)
    else:
        absent = labeling.label_absent(document, field_name="total", user=admin)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == second.status == "superseded"
    assert absent.is_absent and absent.unit_id is None and absent.azure_span == {}
    for run in (first_run, second_run):
        rows = api.get(f"/api/v1/labels/?document={document.pk}&run={run.pk}&status=final").json()[
            "data"
        ]["results"]
        assert [row["id"] for row in rows] == [str(absent.pk)]
        assert _labels(run)[0].is_absent
    if promotion:
        review.act_on_field(field, "correct", admin, value="102")
        present = labeling.promote_field_to_ground_truth(field, admin)
    else:
        present = labeling.label_from_word_ids(
            document,
            run=second_run.pk,
            unit_index=0,
            field_name="total",
            expected_value="102",
            word_ids=["p1:w0"],
            user=admin,
        )
    absent.refresh_from_db()
    assert absent.status == "superseded"
    assert present.version == absent.version + 1 and not present.is_absent
    assert present.unit is not None
    assert present.unit.layout_artifact_id == second_item.layout_artifact_id
    first_span.refresh_from_db()
    assert first_span.unit.layout_artifact_id == first_item.layout_artifact_id
    assert first.azure_span["word_ids"] == ["p1:w0"] and first.expected_value == "100"
    assert list(document.labels.filter(status="final").values_list("pk", flat=True)) == [present.pk]
    for run in (first_run, second_run):
        assert _labels(run)[0].expected_value == "102"


def test_exports_identify_each_historical_geometry_representation(
    document, provider, sample_workflow, admin, monkeypatch, tmp_path
):
    from docai.models import ExtractedField
    from docai.services.export import run_package

    versions = []
    for quality in (None, adaptive(monkeypatch, tmp_path)):
        run = make_run(sample_workflow, document, admin)
        item = run.items.get()
        layouts.get_or_build_layout(document, input_quality=quality, run_item=item)
        label = labeling.label_from_word_ids(
            document,
            run=run.pk,
            unit_index=0,
            field_name="total",
            expected_value="100",
            word_ids=["p1:w0"],
            user=admin,
        )
        assert label.unit is not None
        field = ExtractedField.objects.create(run=run, document=document, name="total")
        SourceSpan.objects.create(
            field=field, unit=label.unit, word_ids=["p1:w0"], polygon=label.azure_span["polygon"]
        )
        versions.append((run, item.layout_artifact_id, label))
    absent = labeling.label_absent(document, field_name="missing", user=admin)
    for run, artifact_id, _ in versions:
        package = run_package(run)
        assert package["fields"][0]["source"]["layout_artifact"] == str(artifact_id)
        exported = {
            row["version"]: row for row in package["ground_truth"] if row["field_name"] == "total"
        }
        for _, expected_artifact, label in versions:
            assert exported[label.version]["layout_artifact"] == str(expected_artifact)
            assert exported[label.version]["azure_span"] == label.azure_span
            assert exported[label.version]["status"] == label.status
        assert (
            next(row for row in package["ground_truth"] if row["field_name"] == absent.field_name)[
                "layout_artifact"
            ]
            is None
        )
