"""Read-only capture and restoration of governed workflow configuration.

Capture chooses versions once. Restoration uses those exact pins rather than
resolving latest versions again. Run creation owns default seeding and publication;
local previews own their detached adapter and citation-repair overrides.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from django.conf import settings

from docai.exceptions import WorkflowConfigError
from docai.models import ExtractionTemplate, PromptVersion, WorkflowConfiguration
from docai.schemas.config import (
    CONFIG_SCHEMAS,
    BaseWorkflowConfig,
    ChunkingConfig,
    ExtractStructuredConfig,
    ExtractTemplateConfig,
    ExtractUnstructuredConfig,
)
from docai.workflows.base import PromptRef
from docai.workflows.prompts import DEFAULTS

from . import governance


@dataclass(frozen=True)
class SnapshotContext:
    """Resolved inputs; execution hooks and concrete adapters remain caller-owned."""

    workflow_type: str
    config: BaseWorkflowConfig
    prompts: dict[str, PromptRef]
    template: dict | None
    layout_adapter_key: str
    llm_adapter_key: str
    deployment: str | None
    parameters: dict


def capture(workflow: WorkflowConfiguration) -> dict[str, Any]:
    """Pin available governed versions without seeding or writing any records."""
    cfg = cast(
        BaseWorkflowConfig,
        CONFIG_SCHEMAS[workflow.workflow_type].model_validate(workflow.config),
    )
    prompt_names = {name for name, _system, _user in DEFAULTS.values()}
    prompt_names.update(cfg.prompt_overrides.values())
    latest: dict[str, PromptVersion] = {}
    for prompt in PromptVersion.objects.filter(name__in=prompt_names).order_by("name", "-version"):
        latest.setdefault(prompt.name, prompt)
    prompts = {}
    for stage, (default_name, _system, _user) in DEFAULTS.items():
        selected = latest.get(cfg.prompt_overrides.get(stage, "")) or latest.get(default_name)
        if selected is None:
            raise WorkflowConfigError("Default prompts are missing. Run seed_defaults first.")
        prompts[stage] = _prompt_pin(selected)
    schemas = {}
    for schema in getattr(cfg, "schemas", []) or []:
        schemas[schema.name] = {"name": schema.name, "version": schema.version}
    schema = (
        cfg.schema_
        if isinstance(cfg, (ExtractStructuredConfig, ExtractUnstructuredConfig))
        else None
    )
    if schema is not None:
        schemas[schema.name] = {"name": schema.name, "version": schema.version}
    template = None
    if isinstance(cfg, ExtractTemplateConfig):
        try:
            tpl = ExtractionTemplate.objects.select_related(
                "schema_version", "prompt_version", "model_config"
            ).get(
                project=workflow.project,
                name=cfg.template_name,
                version=cfg.template_version,
            )
        except ExtractionTemplate.DoesNotExist:
            raise WorkflowConfigError("The pinned extraction template is unavailable.") from None
        template = {
            "name": tpl.name,
            "version": tpl.version,
            "document_type": tpl.document_type,
            "schema": {
                "name": tpl.schema_version.name,
                "version": tpl.schema_version.version,
                "fields": tpl.schema_version.field_definitions,
            },
            "field_guidance": tpl.field_guidance,
            "validations": tpl.validations,
            "chunking": tpl.chunking,
            "prompt": {"name": tpl.prompt_version.name, "version": tpl.prompt_version.version},
            "model": {
                "deployment": tpl.model_config.deployment,
                "parameters": tpl.model_config.parameters,
            },
        }
        prompts["extraction"] = _prompt_pin(tpl.prompt_version)
        schemas[tpl.schema_version.name] = {
            "name": tpl.schema_version.name,
            "version": tpl.schema_version.version,
        }
    return deepcopy(
        {
            "workflow": {
                "id": str(workflow.id),
                "name": workflow.name,
                "version": workflow.version,
                "type": workflow.workflow_type,
                "hash": workflow.content_hash,
                "status": workflow.status,
            },
            "config": cfg.model_dump(mode="json", by_alias=True),
            "prompts": prompts,
            "schemas": schemas,
            "template": template,
            "adapters": {
                "layout": settings.DOCAI["LAYOUT_ADAPTER"],
                "llm": cfg.model.adapter,
            },
            "platform_version": settings.DOCAI["PLATFORM_VERSION"],
        }
    )


def restore(snapshot: dict) -> SnapshotContext:
    """Restore exact pins, accepting legacy snapshots that predate prompt hashes."""
    wf_type = snapshot["workflow"]["type"]
    cfg = cast(BaseWorkflowConfig, CONFIG_SCHEMAS[wf_type].model_validate(snapshot["config"]))
    prompts = {}
    for stage, ref in snapshot["prompts"].items():
        try:
            prompt = PromptVersion.objects.get(name=ref["name"], version=ref["version"])
        except PromptVersion.DoesNotExist:
            raise WorkflowConfigError("A pinned prompt version is unavailable.") from None
        expected_hash = ref.get("hash")
        if expected_hash and expected_hash != governance.content_hash(
            [prompt.system_prompt, prompt.user_template]
        ):
            raise WorkflowConfigError("A pinned prompt no longer matches its captured hash.")
        prompts[stage] = PromptRef(
            name=prompt.name,
            version=prompt.version,
            system=prompt.system_prompt,
            user_template=prompt.user_template,
        )
    template = deepcopy(snapshot.get("template"))
    if template and template.get("chunking"):
        cfg.chunking = ChunkingConfig.model_validate(template["chunking"])
    model = cfg.model
    # Preserve established precedence: workflow parameters configure calls and
    # the template deployment supplies the adapter's deployment fallback.
    deployment = (template or {}).get("model", {}).get("deployment") or model.deployment
    return SnapshotContext(
        workflow_type=wf_type,
        config=cfg,
        prompts=prompts,
        template=template,
        layout_adapter_key=snapshot["adapters"]["layout"],
        llm_adapter_key=snapshot["adapters"]["llm"],
        deployment=deployment,
        parameters=model.model_dump(),
    )


def _prompt_pin(prompt: PromptVersion) -> dict:
    return {"name": prompt.name, "version": prompt.version, "hash": prompt.content_hash}
