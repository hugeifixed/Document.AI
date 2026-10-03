"""Runs and local previews resolve the same governed inputs through one interface."""

from copy import deepcopy

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from docai.exceptions import WorkflowConfigError
from docai.models import ExtractionTemplate, ModelConfiguration, PromptVersion, Run
from docai.services import extraction_preview, governance, runs, workflow_snapshots
from docai.workflows.prompts import DEFAULTS

pytestmark = pytest.mark.django_db


@pytest.fixture(params=["extract_structured", "extract_unstructured", "extract_template"])
def workflow(request, project, admin):
    prompt = governance.new_prompt_version(
        "snapshot-prompt", "extraction", "Pinned instructions", "{content}"
    )
    config = {
        "model": {"adapter": "mock", "deployment": "workflow-deployment", "max_tokens": 321},
        "prompt_overrides": {"extraction": prompt.name},
        "citation_repair": True,
        "chunking": {"strategy": "context_length", "chunk_chars": 4000, "overlap_chars": 200},
    }
    if request.param == "extract_template":
        schema = governance.new_schema_version(
            "snapshot-schema", [{"name": "identifier", "guidance": "Keep leading zeros"}]
        )
        model = ModelConfiguration.objects.create(
            name="snapshot-model",
            adapter="mock",
            deployment="template-deployment",
            parameters={"max_tokens": 987},
        )
        ExtractionTemplate.objects.create(
            project=project,
            name="snapshot-template",
            schema_version=schema,
            prompt_version=prompt,
            model_config=model,
            document_type="invoice",
            field_guidance={"identifier": "Read the issuer's identifier"},
            validations=[{"field": "identifier", "rule": "required"}],
            chunking={"strategy": "page"},
        )
        config.update(template_name="snapshot-template", template_version=1)
    else:
        config["schema"] = {
            "name": "snapshot-schema",
            "version": 3,
            "fields": [{"name": "identifier", "guidance": "Keep leading zeros"}],
        }
        if request.param == "extract_structured":
            config["mode"] = "custom"
    return governance.create_workflow_version(
        project, "snapshot-workflow", request.param, config, admin
    )


def test_run_and_live_preview_share_complete_governed_snapshot(
    workflow, dataset, admin, monkeypatch
):
    calls = []
    original = runs.get_llm

    def get_llm(*args, **kwargs):
        calls.append((args, {key: kwargs[key] for key in ["deployment", "parameters"]}))
        return original(*args, **kwargs)

    monkeypatch.setattr(runs, "get_llm", get_llm)
    run = runs.create_run(workflow.project, workflow, dataset, admin)
    normal = runs.build_context(run)
    with CaptureQueriesContext(connection) as queries:
        preview = extraction_preview.workflow_context(workflow, live=True)
        captured = workflow_snapshots.capture(workflow)
    assert not any(
        query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for query in queries
    )
    assert normal.config == preview.config
    assert normal.prompts == preview.prompts
    assert normal.layout_adapter_key == preview.layout_adapter_key
    assert normal.llm.key == preview.llm.key
    assert calls[0] == calls[1]
    assert {
        key: value for key, value in run.config_snapshot.items() if key != "document_ids"
    } == captured
    assert vars(normal).get("template") == vars(preview).get("template") == captured["template"]
    if captured["template"]:
        assert captured["template"]["model"]["parameters"] == {"max_tokens": 987}
        assert captured["template"]["validations"]
        assert normal.config.model.max_tokens == 321  # Existing workflow precedence.
        assert normal.config.chunking.strategy == "page"


def test_restoring_run_pins_never_selects_newer_versions_or_mutates_snapshot(
    workflow, dataset, admin
):
    run = runs.create_run(workflow.project, workflow, dataset, admin)
    before = deepcopy(run.config_snapshot)
    original = runs.build_context(run)
    ref = before["prompts"]["extraction"]
    newer = governance.new_prompt_version(
        ref["name"], "extraction", "New instructions", "{content}"
    )
    governance.new_schema_version("snapshot-schema", [{"name": "new-field"}])
    restored = runs.build_context(run)
    assert restored.prompts == original.prompts
    assert restored.config == original.config
    assert run.config_snapshot == before
    assert extraction_preview.workflow_context(workflow, live=True).prompts[
        "extraction"
    ].version == (ref["version"] if workflow.workflow_type == "extract_template" else newer.version)
    if before["template"]:
        vars(restored)["template"]["schema"]["fields"][0]["name"] = "changed locally"
        assert (
            vars(runs.build_context(run))["template"]["schema"]["fields"][0]["name"] == "identifier"
        )
        assert run.config_snapshot == before


def test_missing_pinned_prompt_fails_instead_of_substituting_latest(workflow):
    snapshot = workflow_snapshots.capture(workflow)
    snapshot["prompts"]["extraction"]["version"] = 999
    with pytest.raises(WorkflowConfigError, match="pinned prompt version"):
        runs.build_context(Run(config_snapshot=snapshot))


def test_local_overrides_do_not_edit_workflow_or_seed_missing_defaults(workflow):
    before = deepcopy(workflow.config)
    with CaptureQueriesContext(connection) as queries:
        ctx = extraction_preview.workflow_context(workflow, live=False, citation_repair=False)
    assert ctx.llm.key == "mock" and ctx.layout_adapter_key == "pypdf"
    assert not ctx.config.citation_repair
    assert workflow.config == before
    workflow.refresh_from_db()
    assert workflow.config == before
    assert not any(
        query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for query in queries
    )
    name = DEFAULTS["generic_kv"][0]
    PromptVersion.objects.filter(name=name).delete()
    with pytest.raises(WorkflowConfigError, match="Default prompts are missing"):
        extraction_preview.workflow_context(workflow, live=False)
    assert not PromptVersion.objects.filter(name=name).exists()


def test_restore_validates_prompt_hash_and_reads_legacy_snapshots(workflow):
    snapshot = workflow_snapshots.capture(workflow)
    ref = snapshot["prompts"]["extraction"]
    legacy = deepcopy(snapshot)
    for pin in legacy["prompts"].values():
        pin.pop("hash", None)
    assert (
        runs.build_context(Run(config_snapshot=legacy)).prompts["extraction"].version
        == ref["version"]
    )
    PromptVersion.objects.filter(name=ref["name"], version=ref["version"]).update(
        system_prompt="Out-of-band mutation"
    )
    with pytest.raises(WorkflowConfigError, match="captured hash"):
        runs.build_context(Run(config_snapshot=snapshot))


def test_missing_template_pin_is_explicit_and_project_scoped(project, admin):
    workflow = governance.create_workflow_version(
        project,
        "missing-template",
        "extract_template",
        {"template_name": "missing", "template_version": 7},
        admin,
    )
    with pytest.raises(WorkflowConfigError, match="pinned extraction template"):
        extraction_preview.workflow_context(workflow, live=False)


def test_run_creation_can_seed_defaults_without_making_preview_write(project, dataset, admin):
    workflow = governance.create_workflow_version(
        project, "fresh-defaults", "extract_structured", {"mode": "default"}, admin
    )
    PromptVersion.objects.all().delete()
    with pytest.raises(WorkflowConfigError, match="Default prompts are missing"):
        extraction_preview.workflow_context(workflow, live=False)
    run = runs.create_run(project, workflow, dataset, admin)
    assert len(run.prompt_versions) == len(DEFAULTS)
    assert extraction_preview.workflow_context(workflow, live=False).prompts
