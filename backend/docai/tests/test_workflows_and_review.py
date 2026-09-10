import pytest

from docai.adapters.llm.base import LLMCall, get_llm
from docai.exceptions import InvalidModelOutput
from docai.models import ExtractedField, GroundTruthLabel, ReviewAction, Segment
from docai.schemas.llm import SegmentationOut, SegmentOut
from docai.services import evaluation as eval_svc
from docai.services import ingestion, review
from docai.services import runs as run_svc
from docai.workflows.unbundle import validate_segments

pytestmark = pytest.mark.django_db


def test_mock_llm_rejects_invalid_output():
    llm = get_llm("mock")
    with pytest.raises(InvalidModelOutput):   # canned response missing required fields is rejected, never coerced
        llm.invoke(LLMCall(system="s", user="u", schema=SegmentOut, mock_context={"canned": {"start_unit": 0}}))
    ok = llm.invoke(LLMCall(system="s", user="u", schema=SegmentationOut, mock_context={"unit_texts": ["Form W-2 Wage and Tax Statement"]}))
    assert ok.parsed.segments[0].category == "w2"


def test_segment_validation_orders_fills_and_falls_back():
    assert validate_segments([{"start_unit": 2, "end_unit": 3, "category": "a"}, {"start_unit": 0, "end_unit": 0, "category": "b"}], 5) == \
        [{"start": 0, "end": 1, "category": "b", "confidence": None, "evidence": "", "continuation_of": None, "sources": []},
         {"start": 2, "end": 4, "category": "a", "confidence": None, "evidence": "", "continuation_of": None, "sources": []}]
    assert validate_segments([{"start_unit": 0, "end_unit": 9, "category": "a"}, {"start_unit": 0, "end_unit": 9, "category": "b"}], 3)[0]["end"] == 2
    assert validate_segments([], 3) is None


def test_end_to_end_run_with_snapshot_grounding_and_metrics(project, dataset, admin, sample_workflow, w2_pdf, package_pdf):
    d1 = ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    d2 = ingestion.ingest_upload(dataset, package_pdf.filename, package_pdf.data, user=admin)
    for name, val in w2_pdf.fields.items():
        GroundTruthLabel.objects.create(document=d1, kind="field", field_name=name, expected_value=val, status="final", version=1)
    for seg in package_pdf.segments:
        GroundTruthLabel.objects.create(document=d2, kind="segment", category=seg["category"], segment_start=seg["start"],
                                        segment_end=seg["end"], status="final", version=1)
    run = run_svc.create_run(project, sample_workflow, dataset, admin, name="t")
    assert run.config_hash.startswith("sha256:") and run.prompt_versions["extraction"]["name"] == "default-extraction"
    run = run_svc.execute_run(run.id)
    assert run.status == "succeeded" and run.processed_items == 2
    assert Segment.objects.filter(run=run, document=d2).count() == 3
    fields = ExtractedField.objects.filter(run=run, document=d1)
    ssn = fields.get(name="employee_ssn")
    assert ssn.raw_value == w2_pdf.fields["employee_ssn"] and ssn.grounded and ssn.spans.first().word_ids
    assert ssn.normalized_value == w2_pdf.fields["employee_ssn"].replace("-", "")
    m = run.metrics
    assert m["has_ground_truth"] and m["extraction"]["aggregate"]["precision"] == 1.0
    assert m["segmentation"]["aggregate"]["exact_segment_match_rate"] == 1.0
    # idempotent re-processing replaces, never duplicates
    item = run.items.get(document=d1)
    run_svc.process_item(item.id)
    assert ExtractedField.objects.filter(run=run, document=d1).count() == fields.count()


def test_async_runner_does_not_finalize_before_worker_callback(
    project, dataset, admin, sample_workflow, w2_pdf, monkeypatch
):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.create_run(project, sample_workflow, dataset, admin)

    class FakeAsyncRunner:
        is_async = True

        def map(self, fn, ids, **meta):
            assert fn is run_svc.process_item
            assert len(list(ids)) == 1
            assert meta["run_id"] == str(run.id)
            return True

    monkeypatch.setattr("docai.tasks.runner.get_runner", lambda: FakeAsyncRunner())
    returned = run_svc.execute_run(run.id)

    assert returned.status == "running"
    assert returned.finished_at is None
    assert returned.items.get().status == "queued"


def test_review_preserves_original_and_promotes_versioned_gt(project, dataset, admin, reviewer, sample_workflow, w2_pdf):
    d1 = ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.execute_run(run_svc.create_run(project, sample_workflow, dataset, admin).id)
    f = ExtractedField.objects.get(run=run, document=d1, name="wages_box1")
    original = f.raw_value
    review.act_on_field(f, "correct", reviewer, value="1.00", reason="typo")
    f.refresh_from_db()
    assert f.raw_value == original and f.reviewed_value == "1.00" and f.review_status == "corrected"
    assert ReviewAction.objects.filter(field=f, action="correct").exists()
    lb1 = review.promote_field_to_ground_truth(f, admin, "verified")
    review.act_on_field(f, "correct", reviewer, value="2.00")
    lb2 = review.promote_field_to_ground_truth(f, admin)
    lb1.refresh_from_db()
    assert (lb1.version, lb2.version, lb1.status, lb2.status) == (1, 2, "superseded", "final")
    assert review.history_for_field(f)[0]["action"] == "correct"


def test_split_and_merge_segments(project, dataset, admin, reviewer, sample_workflow, package_pdf):
    d2 = ingestion.ingest_upload(dataset, package_pdf.filename, package_pdf.data, user=admin)
    run = run_svc.execute_run(run_svc.create_run(project, sample_workflow, dataset, admin).id)
    seg = Segment.objects.get(run=run, document=d2, index=1)   # subpoena pages 1-2
    first, second = review.split_segment(seg, reviewer, at_unit=2)
    assert (first.start_unit, first.end_unit, second.start_unit, second.end_unit) == (1, 1, 2, 2)
    assert Segment.objects.get(run=run, document=d2, index=3).category == "paystub"
    merged = review.merge_segments(first, second, reviewer)
    assert (merged.start_unit, merged.end_unit) == (1, 2) and Segment.objects.filter(run=run, document=d2).count() == 3


def test_quality_indicators_without_ground_truth(project, dataset, admin, sample_workflow, w2_pdf):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.execute_run(run_svc.create_run(project, sample_workflow, dataset, admin).id)
    ev = eval_svc.create_evaluation(run, admin)
    assert not ev.has_ground_truth and ev.metrics["quality_indicators"]["kind"] == "quality_indicators"
    assert "accuracy" not in str(ev.metrics["quality_indicators"]["per_field"])


def test_structured_rules_workflow_and_llm_fallback(project, dataset, admin, w2_pdf):
    from docai.management.commands.seed_defaults import sample_workflow_configs
    from docai.services import governance
    wt, cfg = sample_workflow_configs()["classify-structured-rules"]
    wf = governance.create_workflow_version(project, "rules", wt, cfg, admin)
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.execute_run(run_svc.create_run(project, wf, dataset, admin).id)
    c = run.classifications.get()
    assert c.category == "w2" and c.method == "rules" and c.rule_score >= 2 and c.matched_evidence and c.rule_version


def test_export_formats_are_utf8(project, dataset, admin, sample_workflow, w2_pdf, api):
    ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.execute_run(run_svc.create_run(project, sample_workflow, dataset, admin).id)
    r = api.get(f"/api/v1/runs/{run.id}/export/json/")
    assert r.status_code == 200 and "charset=utf-8" in r["Content-Type"]
    assert "private" in r["Cache-Control"] and "no-store" in r["Cache-Control"]
    import json
    pkg = json.loads(r.content.decode("utf-8"))
    assert pkg["run"]["config_hash"] == run.config_hash and pkg["fields"][0]["source"]
    csv = api.get(f"/api/v1/runs/{run.id}/export/csv/").content.decode("utf-8")
    assert csv.startswith("\ufeff") and "source.unit_index" in csv.splitlines()[0]
    assert api.get(f"/api/v1/runs/{run.id}/export/xlsx/").status_code == 200


def test_content_masked_for_viewers(project, dataset, admin, viewer, sample_workflow, w2_pdf):
    from rest_framework.test import APIClient
    document = ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    run = run_svc.execute_run(run_svc.create_run(project, sample_workflow, dataset, admin).id)
    field = ExtractedField.objects.filter(run=run).exclude(raw_value__in=(None, "")).first()
    review.act_on_field(
        field, "correct", admin, value="private correction", reason="private reason"
    )

    c = APIClient()
    c.force_authenticate(viewer)
    rows = c.get(f"/api/v1/fields/?run={run.id}").json()["data"]["results"]
    assert rows and all(r["raw_value"] in (None, "", "•••") for r in rows)
    assert all(span["text"] == "•••" for row in rows for span in row["spans"] if span["text"])
    assert c.get(f"/api/v1/runs/{run.id}/export/json/").status_code == 403
    assert c.get(f"/api/v1/fields/{field.id}/history/").status_code == 403
    actions = c.get(f"/api/v1/review-actions/?field={field.id}").json()["data"]["results"]
    assert actions[0]["before"] == actions[0]["after"] == actions[0]["reason"] == "•••"
    events = c.get(f"/api/v1/audit-events/?object_id={field.id}").json()["data"]["results"]
    assert events[0]["before_ref"] == events[0]["after_ref"] == events[0]["reason"] == "•••"
    assert c.get(f"/api/v1/documents/{document.id}/original/").status_code == 403

    c.force_authenticate(admin)
    admin_rows = c.get(f"/api/v1/fields/?run={run.id}").json()["data"]["results"]
    assert any(r["raw_value"] not in (None, "", "•••") for r in admin_rows)
    original = c.get(f"/api/v1/documents/{document.id}/original/")
    assert original.streaming
    assert original["Content-Security-Policy"] == "sandbox"
    assert "private" in original["Cache-Control"] and "no-store" in original["Cache-Control"]
    original.close()


def test_logging_sanitizer_redacts_secrets_and_pii():
    from docai.logging.sanitize import sanitize_extra, sanitize_text
    t = sanitize_text("ssn 766-16-2186 card 4111 1111 1111 1111 Authorization: Bearer abc.def token=xyz mail a@b.co")
    assert "766-16-2186" not in t and "4111" not in t and "abc.def" not in t and "xyz" not in t and "a@b.co" not in t
    assert sanitize_extra({"api_key": "k", "x": {"password": "p"}, "ok": 1}) == {"api_key": "[REDACTED]", "x": {"password": "[REDACTED]"}, "ok": 1}
