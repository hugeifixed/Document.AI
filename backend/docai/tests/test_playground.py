"""The playground produces proposals, never active workflows or dataset uploads."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from loguru import logger
from rest_framework.test import APIClient

from docai.exceptions import IntegrationError, InvalidModelOutput, ValidationFailed
from docai.logging.context import get_trace_id, reset_trace_id, set_trace_id
from docai.models import (
    PlaygroundSample,
    PlaygroundSession,
    PlaygroundUsageEvent,
    WorkflowConfiguration,
)
from docai.schemas.playground import PlaygroundProposal, compile_proposal
from docai.services import governance, ingestion, playground

pytestmark = pytest.mark.django_db
ROOT = "/api/v1/workflow-playground/sessions/"


def proposal(workflow_type="extract_structured"):
    document = {
        "key": "w2",
        "name": "Form W-2",
        "description": "Wage statement",
        "distinguishing_evidence": "Form W-2 heading",
        "continuation_characteristics": "Keep W-2 continuation pages with this form",
        "fields": [
            {
                "name": "wages_box1",
                "description": "Box 1 wages",
                "type": "currency",
                "observed": True,
                "sample_index": 0,
                "unit": 1,
                "source_label": "Wages",
            }
        ],
    }
    return PlaygroundProposal.model_validate(
        {
            "workflow_type": workflow_type,
            "documents": [document, {**document, "key": "note", "name": "Promissory note"}]
            if workflow_type == "unbundle_classify_extract"
            else [document],
        }
    )


@pytest.mark.parametrize(
    "kind",
    [
        "extract_structured",
        "extract_unstructured",
        "unbundle_classify_extract",
    ],
)
def test_compiled_proposals_pass_existing_validator_and_default_to_review(kind, api):
    config = compile_proposal(proposal(kind))
    validated = governance.validate_workflow(kind, config)
    response = api.post(
        "/api/v1/workflows/validate/", {"workflow_type": kind, "config": config}, format="json"
    )
    assert response.status_code == 200, response.content
    assert response.json()["data"]["valid"] is True
    assert validated["routing"] == [{"when": {}, "outcome": "human_review"}]
    assert "model" not in config
    assert "source_label" not in str(config)
    assert WorkflowConfiguration.objects.count() == 0


def test_compiler_keeps_guidance_and_bundle_cues_without_sample_values():
    proposed = proposal("unbundle_classify_extract")
    proposed.documents[0].fields[0].guidance = "Copy the printed amount; blank means null."
    body = compile_proposal(proposed)
    assert body["categories"][0]["continuation_characteristics"] == (
        "Keep W-2 continuation pages with this form"
    )
    assert body["schemas"][0]["fields"][0]["guidance"] == (
        "Copy the printed amount; blank means null."
    )
    assert "source_label" not in str(body)
    assert "sample_index" not in str(body)


def test_enum_needs_explicit_choices_and_variable_rows_need_guidance():
    proposed = proposal().model_dump()
    field = proposed["documents"][0]["fields"][0]
    field["type"] = "enum"
    with pytest.raises(ValueError, match="explicit choices"):
        PlaygroundProposal.model_validate(proposed)
    field["enum_values"] = ["fixed", "variable"]
    body = compile_proposal(PlaygroundProposal.model_validate(proposed))
    assert body["schema"]["fields"][0]["enum"] == ["fixed", "variable"]
    field["type"] = "list"
    field["enum_values"] = []
    field["variable_rows"] = True
    with pytest.raises(ValueError, match="guidance"):
        PlaygroundProposal.model_validate(proposed)


def test_observed_label_accepts_layout_whitespace_and_punctuation():
    proposed = proposal()
    proposed.documents[0].fields[0].source_label = "Wages, tips"

    checked = playground._verified_proposal(
        proposed, [{"units": [{"text": "1 Wages,\n  tips and other compensation"}]}]
    )

    assert checked.documents[0].fields[0].observed is True
    assert checked.documents[0].fields[0].unit == 1


def test_suggested_fields_cannot_retain_source_claims():
    proposed = proposal().model_dump()
    field = proposed["documents"][0]["fields"][0]
    field["observed"] = False

    checked = PlaygroundProposal.model_validate(proposed)

    assert (
        checked.documents[0].fields[0].sample_index,
        checked.documents[0].fields[0].unit,
        checked.documents[0].fields[0].source_label,
    ) == (None, None, "")


@pytest.mark.parametrize(
    ("label", "unit", "pages"),
    [
        ("Box 1", 1, ["Box 11 wages"]),
        ("Wages", 2, ["Wages", "Other text"]),
        ("Wages", 2, ["Wages"]),
    ],
)
def test_unverified_observed_label_becomes_a_suggestion(label, unit, pages):
    proposed = proposal()
    field = proposed.documents[0].fields[0]
    field.source_label = label
    field.unit = unit

    checked = playground._verified_proposal(
        proposed, [{"units": [{"text": text} for text in pages]}]
    )

    assert field.observed is False
    assert (field.sample_index, field.unit, field.source_label) == (None, None, "")
    assert governance.validate_workflow("extract_structured", compile_proposal(checked))


def test_operator_only_session_and_private_upload(
    api, project, operator, viewer, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    other = APIClient()
    other.force_authenticate(viewer)
    assert other.post(ROOT, {"project": str(project.pk)}, format="json").status_code == 403
    response = api.post(ROOT, {"project": str(project.pk)}, format="json")
    assert response.status_code == 201
    sid = response.json()["data"]["id"]
    client = APIClient()
    client.force_authenticate(operator)
    assert client.get(f"{ROOT}{sid}/").status_code == 404
    added = api.post(
        f"{ROOT}{sid}/samples/",
        {"file": SimpleUploadedFile("sample.txt", b"Wages: 123\n")},
        format="multipart",
    )
    assert added.status_code == 201, added.content
    assert added.json()["data"]["samples"][0]["source_kind"] == "temporary"
    assert WorkflowConfiguration.objects.count() == 0
    session = PlaygroundSession.objects.get(pk=sid)
    path = session.samples.get().storage_path
    assert default_storage.exists(path)
    cleared = api.delete(f"{ROOT}{sid}/samples/delete/")
    assert cleared.status_code == 200
    assert cleared.json()["data"]["samples"] == []
    assert cleared.json()["data"]["status"] == "ready"
    assert not default_storage.exists(path)


def test_failed_sample_metadata_write_removes_uploaded_file(
    api, project, settings, tmp_path, monkeypatch
):
    settings.MEDIA_ROOT = tmp_path
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    save = PlaygroundSample.save

    def fail_metadata_write(self, *args, **kwargs):
        if kwargs.get("update_fields") == ["storage_path"]:
            raise RuntimeError("sample metadata write failed")
        return save(self, *args, **kwargs)

    monkeypatch.setattr(PlaygroundSample, "save", fail_metadata_write)
    with pytest.raises(RuntimeError, match="sample metadata write failed"):
        playground.attach_upload(session, SimpleUploadedFile("sample.txt", b"Wages: 123\n"))

    assert not session.samples.exists()
    assert not any(path.is_file() for path in (tmp_path / "playground").rglob("*"))


def test_revoked_project_access_hides_existing_session(api, project, monkeypatch):
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    monkeypatch.setattr("docai.api.permissions.can_access_project", lambda _user, _project: False)
    monkeypatch.setattr("docai.api.playground.can_access_project", lambda _user, _project: False)
    assert api.get(ROOT).json()["data"] == []
    assert api.get(f"{ROOT}{sid}/").status_code == 404


def test_sample_limits_and_expiry(api, project, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    for i in range(3):
        playground.attach_upload(session, SimpleUploadedFile(f"s{i}.txt", b"Label: value\n"))
    with pytest.raises(ValidationFailed, match="three samples"):
        playground.attach_upload(session, SimpleUploadedFile("fourth.txt", b"Label: value\n"))
    paths = [sample.storage_path for sample in session.samples.all()]
    session.expires_at = timezone.now() - timedelta(seconds=1)
    session.save(update_fields=["expires_at"])
    assert api.get(f"{ROOT}{sid}/").status_code == 404
    assert playground.cleanup_expired() == 1
    assert all(not default_storage.exists(path) for path in paths)


def test_usage_survives_session_expiry_without_sample_content(api, project):
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    event = PlaygroundUsageEvent.objects.create(
        session=session,
        project_id_snapshot=project.pk,
        stage="generate",
        deployment="test-deployment",
        input_tokens=120,
        cached_input_tokens=32,
        output_tokens=18,
        outcome="succeeded",
        created_by=session.created_by,
    )
    session.expires_at = timezone.now() - timedelta(seconds=1)
    session.save(update_fields=["expires_at"])
    assert playground.cleanup_expired() == 1
    event.refresh_from_db()
    assert event.session is None
    assert event.project_id_snapshot == project.pk


def test_total_page_and_byte_limits(api, project):
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    PlaygroundSample.objects.create(
        session=session,
        filename="a.txt",
        file_format="txt",
        size_bytes=49_999_999,
        unit_count=29,
        created_by=session.created_by,
    )
    with pytest.raises(ValidationFailed, match="30 pages"):
        playground._check_capacity(session, size=0, units=2)
    with pytest.raises(ValidationFailed, match="50 MB"):
        playground._check_capacity(session, size=2, units=1)
    playground._check_capacity(session, size=1, units=1)


def test_existing_document_is_referenced_without_copy(
    api, project, dataset, admin, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    document = ingestion.ingest_upload(dataset, "existing.txt", b"Total: 100\n", user=admin)
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    added = api.post(f"{ROOT}{sid}/documents/", {"document_id": str(document.pk)}, format="json")
    assert added.status_code == 201, added.content
    assert added.json()["data"]["samples"][0]["document_id"] == str(document.pk)
    repeated = api.post(f"{ROOT}{sid}/documents/", {"document_id": str(document.pk)}, format="json")
    assert repeated.status_code == 409
    assert repeated.json()["error_code"] == "PLAYGROUND_DOCUMENT_ALREADY_SELECTED"
    sample = PlaygroundSession.objects.get(pk=sid).samples.get()
    assert sample.document_id == document.pk
    assert sample.storage_path == ""
    assert api.delete(f"{ROOT}{sid}/").status_code == 200
    document.refresh_from_db()
    assert default_storage.exists(document.storage_path)


@pytest.mark.parametrize("source", ["upload", "dataset"])
def test_adding_example_invalidates_proposal_from_previous_samples(
    api, project, dataset, admin, settings, tmp_path, source
):
    settings.MEDIA_ROOT = tmp_path
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    session.status = "complete"
    session.workflow_type = "extract_structured"
    session.proposal = proposal().model_dump()
    session.save(update_fields=["status", "workflow_type", "proposal"])

    if source == "upload":
        response = api.post(
            f"{ROOT}{sid}/samples/",
            {"file": SimpleUploadedFile("new.txt", b"New field: value\n")},
            format="multipart",
        )
    else:
        document = ingestion.ingest_upload(dataset, "new.txt", b"New field: value\n", user=admin)
        response = api.post(
            f"{ROOT}{sid}/documents/", {"document_id": str(document.pk)}, format="json"
        )

    assert response.status_code == 201, response.content
    assert response.json()["data"]["status"] == "ready"
    assert response.json()["data"]["proposal"] == {}
    assert response.json()["data"]["config"] is None
    session.refresh_from_db()
    assert session.proposal == {}


def test_resume_lists_most_recent_activity_first(api, project, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    first = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    second = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    first_session = PlaygroundSession.objects.get(pk=first)
    before = first_session.last_activity_at
    uploaded = api.post(
        f"{ROOT}{first}/samples/",
        {"file": SimpleUploadedFile("sample.txt", b"Label: value\n")},
        format="multipart",
    )
    assert uploaded.status_code == 201
    first_session.refresh_from_db()
    assert first_session.last_activity_at > before
    assert uploaded.json()["data"]["last_activity_at"]
    listed = api.get(ROOT, {"project": str(project.pk)})
    assert [item["id"] for item in listed.json()["data"][:2]] == [first, second]
    assert listed.json()["data"][0]["last_activity_at"]


def test_scanned_samples_require_ocr_adapter(api, project, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    sample = playground.attach_upload(
        session, SimpleUploadedFile("scan.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    )
    with pytest.raises(ValidationFailed, match="OCR-capable"):
        playground._sample_layout(sample)


def test_incomplete_page_coverage_is_rejected(api, project, settings, tmp_path, monkeypatch):
    from docai.schemas.layout import LayoutDocument, LayoutPage

    settings.MEDIA_ROOT = tmp_path
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    sample = playground.attach_upload(session, SimpleUploadedFile("sample.txt", b"Total: 100\n"))
    sample.unit_count = 2
    sample.save(update_fields=["unit_count"])

    class IncompleteProvider:
        supports_ocr = True

        def analyze(self, *args, **kwargs):
            return LayoutDocument(
                document_id=str(sample.pk),
                source_format="txt",
                service="fixture",
                units=[LayoutPage(index=0, number=1, content="Total: 100")],
            )

    monkeypatch.setattr(
        playground, "get_layout_provider_for_format", lambda _fmt: IncompleteProvider()
    )
    with pytest.raises(IntegrationError) as error:
        playground._sample_layout(sample)
    assert error.value.error_code == "INCOMPLETE_LAYOUT"


def test_generation_uses_existing_layout_and_mock_adapter(api, project, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    playground.attach_upload(
        session, SimpleUploadedFile("sample.txt", b"Wages: 123\nDate: 2026-01-01\n")
    )
    playground._process(sid, "Extract the wages", "extract_structured", "")
    session.refresh_from_db()
    assert session.status == "complete", session.error_message
    assert session.proposal["documents"][0]["fields"][0]["required"] is False
    assert session.proposal["documents"][0]["fields"][0]["observed"] is True
    assert playground.result(session)["config"]["schema"]["fields"]
    assert WorkflowConfiguration.objects.count() == 0


def test_generation_keeps_unverified_evidence_as_a_suggestion(
    api, project, settings, tmp_path, monkeypatch
):
    settings.MEDIA_ROOT = tmp_path
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    playground.attach_upload(session, SimpleUploadedFile("sample.txt", b"Wages: 123\n"))
    proposed = proposal().model_dump()
    proposed["documents"][0]["fields"][0]["source_label"] = "Box 99"
    monkeypatch.setattr(
        playground,
        "get_llm",
        lambda **_kwargs: SimpleNamespace(invoke=lambda _call: SimpleNamespace(parsed=proposed)),
    )

    playground._process(sid, "Extract wages", "extract_structured", "")

    session.refresh_from_db()
    assert session.status == "complete", session.error_message
    field = session.proposal["documents"][0]["fields"][0]
    assert field["observed"] is False
    assert (field["sample_index"], field["unit"], field["source_label"]) == (None, None, "")
    assert playground.result(session)["config"] is not None


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (
            IntegrationError("Only 2 of 3 pages", error_code="INCOMPLETE_LAYOUT"),
            "INCOMPLETE_LAYOUT",
        ),
        (InvalidModelOutput(), "INVALID_MODEL_OUTPUT"),
        (IntegrationError("truncated", error_code="LLM_OUTPUT_TRUNCATED"), "LLM_OUTPUT_TRUNCATED"),
    ],
)
def test_failed_generation_is_actionable_and_never_publishes_json(
    api,
    project,
    settings,
    tmp_path,
    monkeypatch,
    failure,
    code,
):
    settings.MEDIA_ROOT = tmp_path
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    playground.attach_upload(session, SimpleUploadedFile("sample.txt", b"Wages: 123\n"))
    if code == "INCOMPLETE_LAYOUT":
        monkeypatch.setattr(
            playground, "_sample_layout", lambda _sample: (_ for _ in ()).throw(failure)
        )
    else:

        class Broken:
            def invoke(self, _call):
                raise failure

        monkeypatch.setattr(playground, "get_llm", lambda **_kwargs: Broken())
    records = []
    sink = logger.add(
        lambda message: records.append(message.record),
        filter=lambda record: record["message"] == "Playground generation failed",
    )
    prior_trace = get_trace_id()
    try:
        playground._process(sid, "Extract wages", "extract_structured", "", "playgroundtrace123")
    finally:
        logger.remove(sink)
    assert get_trace_id() == prior_trace
    assert records[-1]["extra"]["trace_id"] == "playgroundtrace123"
    assert records[-1]["extra"]["error_code"] == code
    session.refresh_from_db()
    assert session.status == "failed"
    assert session.error_code == code
    assert session.proposal == {}
    assert playground.result(session)["config"] is None


def test_concurrent_generation_rejected(
    api, project, monkeypatch, django_capture_on_commit_callbacks
):
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    submissions = []
    monkeypatch.setattr(playground._POOL, "submit", lambda *args: submissions.append(args))
    token = set_trace_id("playgroundrequest123")
    try:
        with django_capture_on_commit_callbacks(execute=True):
            playground.queue_generation(
                session, goal="Extract totals", workflow_type="extract_structured"
            )
    finally:
        reset_trace_id(token)
    assert submissions[0][-2] == "playgroundrequest123"
    assert UUID(submissions[0][-1])
    with pytest.raises(Exception, match="already has a generation"):
        playground.queue_generation(
            session, goal="Extract totals", workflow_type="extract_structured"
        )


def test_lost_worker_session_can_be_retried(api, project, admin, monkeypatch):
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    session.status = "queued"
    session.state_changed_at = timezone.now() - timedelta(hours=2)
    session.save(update_fields=["status", "state_changed_at"])
    resumed = playground.get_session(sid, admin)
    assert resumed.status == "failed"
    assert resumed.error_code == "PLAYGROUND_WORKER_LOST"
    monkeypatch.setattr(playground._POOL, "submit", lambda *_args: None)
    playground.queue_generation(resumed, goal="Extract totals", workflow_type="extract_structured")
    resumed.refresh_from_db()
    assert resumed.status == "queued"


def test_superseded_worker_cannot_overwrite_new_attempt(
    api, project, admin, monkeypatch, django_capture_on_commit_callbacks
):
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    submissions = []
    monkeypatch.setattr(playground._POOL, "submit", lambda *args: submissions.append(args))

    with django_capture_on_commit_callbacks(execute=True):
        playground.queue_generation(
            session, goal="First proposal", workflow_type="extract_structured"
        )
    session.refresh_from_db()
    session.state_changed_at = timezone.now() - timedelta(hours=2)
    session.save(update_fields=["state_changed_at"])

    recovered = playground.get_session(sid, admin)
    with django_capture_on_commit_callbacks(execute=True):
        playground.queue_generation(
            recovered, goal="Replacement proposal", workflow_type="extract_structured"
        )

    old_worker = submissions[0]
    old_worker[0](*old_worker[1:])
    session.refresh_from_db()

    assert session.status == "queued"
    assert session.goal == "Replacement proposal"
    assert session.generation_attempt == UUID(submissions[1][-1])
    assert session.proposal == {}


def test_lost_worker_check_does_not_overwrite_a_completed_generation(
    api, project, admin, monkeypatch
):
    from django.db.models import QuerySet

    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    session.status = "generating"
    session.state_changed_at = timezone.now() - timedelta(hours=2)
    session.save(update_fields=["status", "state_changed_at"])
    update = QuerySet.update

    def finish_before_stale_update(self, **kwargs):
        if self.model is PlaygroundSession and kwargs.get("error_code") == "PLAYGROUND_WORKER_LOST":
            update(
                PlaygroundSession.objects.filter(pk=sid),
                status="complete",
                state_changed_at=timezone.now(),
            )
        return update(self, **kwargs)

    monkeypatch.setattr(QuerySet, "update", finish_before_stale_update)
    resumed = playground.get_session(sid, admin)
    assert resumed.status == "complete"
    assert resumed.error_code == ""


def test_edit_required_flag_compiles_without_creating_workflow(api, project):
    sid = api.post(ROOT, {"project": str(project.pk)}, format="json").json()["data"]["id"]
    session = PlaygroundSession.objects.get(pk=sid)
    session.status = "complete"
    session.workflow_type = "extract_structured"
    session.proposal = proposal().model_dump()
    session.save(update_fields=["status", "workflow_type", "proposal"])
    edited = proposal().model_dump()
    edited["documents"][0]["fields"][0]["required"] = True
    response = api.put(f"{ROOT}{sid}/proposal/", edited, format="json")
    assert response.status_code == 200, response.content
    assert response.json()["data"]["config"]["schema"]["fields"][0]["required"] is True
    assert WorkflowConfiguration.objects.count() == 0
