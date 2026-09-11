"""Versioning + approval. Nothing is auto-promoted: approval is an explicit,
audited action by an authorized user. Content hashes make snapshots
tamper-evident (ported from the prototype's freeze manifest)."""

from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from docai.exceptions import Conflict, PermissionDenied, WorkflowConfigError
from docai.models import (
    CONFIG_STATUS,
    CategoryDefinition,
    ExtractionTemplate,
    Project,
    PromptVersion,
    SchemaVersion,
    WorkflowConfiguration,
)
from docai.schemas.config import validate_workflow_config
from docai.workflows.prompts import DEFAULTS

from . import audit


def content_hash(obj) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
    )


@transaction.atomic
def create_category_version(
    project: Project,
    key: str,
    *,
    user=None,
    previous: CategoryDefinition | None = None,
    **values,
) -> CategoryDefinition:
    """Allocate an immutable category revision under a stable project lock."""
    Project.objects.select_for_update().only("pk").get(pk=project.pk)
    last = CategoryDefinition.objects.filter(project=project, key=key).order_by("-version").first()
    if last is not None and previous is None:
        raise Conflict(
            "This category key already exists. Create a revision from its detail resource."
        )
    source = previous or last

    def value(name, default=""):
        return values[name] if name in values else getattr(source, name, default)

    category = CategoryDefinition.objects.create(
        project=project,
        key=key,
        version=(last.version + 1 if last else 1),
        name=value("name"),
        description=value("description"),
        distinguishing_evidence=value("distinguishing_evidence"),
        aliases=value("aliases", []),
        continuation_characteristics=value("continuation_characteristics"),
        created_by=user,
        updated_by=user,
    )
    audit.record(
        user,
        "category.version_created",
        category,
        after={"key": key, "version": category.version},
    )
    return category


def ensure_default_prompts(user=None) -> dict[str, PromptVersion]:
    out = {}
    for purpose, (name, system, template) in DEFAULTS.items():
        pv = PromptVersion.objects.filter(name=name).order_by("-version").first()
        if pv is None:
            pv = PromptVersion.objects.create(
                name=name,
                version=1,
                purpose=purpose,
                system_prompt=system,
                user_template=template,
                content_hash=content_hash([system, template]),
                created_by=user,
            )
        out[purpose] = pv
    return out


def new_prompt_version(
    name: str, purpose: str, system_prompt: str, user_template: str, user=None
) -> PromptVersion:
    last = PromptVersion.objects.filter(name=name).order_by("-version").first()
    pv = PromptVersion.objects.create(
        name=name,
        version=(last.version + 1 if last else 1),
        purpose=purpose,
        system_prompt=system_prompt,
        user_template=user_template,
        content_hash=content_hash([system_prompt, user_template]),
        created_by=user,
    )
    audit.record(user, "prompt.version_created", pv, after={"name": name, "version": pv.version})
    return pv


def new_schema_version(name: str, field_definitions: list[dict], user=None) -> SchemaVersion:
    from docai.schemas.config import ExtractionSchemaConfig, FieldSpec

    last = SchemaVersion.objects.filter(name=name).order_by("-version").first()
    version = last.version + 1 if last else 1
    cfg = ExtractionSchemaConfig(
        name=name,
        version=version,
        fields=[FieldSpec.model_validate(item) for item in field_definitions],
    )
    sv = SchemaVersion.objects.create(
        name=name,
        version=version,
        json_schema=cfg.model_json_schema(),
        field_definitions=[f.model_dump() for f in cfg.fields],
        created_by=user,
    )
    audit.record(user, "schema.version_created", sv, after={"name": name, "version": version})
    return sv


def create_workflow_version(
    project, name: str, workflow_type: str, config: dict, user=None
) -> WorkflowConfiguration:
    try:
        validated = validate_workflow_config(workflow_type, config)
    except ValueError as exc:
        raise WorkflowConfigError(errors={"config": str(exc)[:500]}) from None
    last = (
        WorkflowConfiguration.objects.filter(project=project, name=name)
        .order_by("-version")
        .first()
    )
    wf = WorkflowConfiguration.objects.create(
        project=project,
        name=name,
        version=(last.version + 1 if last else 1),
        workflow_type=workflow_type,
        config=validated,
        content_hash=content_hash(validated),
        created_by=user,
        updated_by=user,
    )
    audit.record(
        user, "workflow.version_created", wf, after={"version": wf.version, "hash": wf.content_hash}
    )
    return wf


@transaction.atomic
def approve_workflow(wf: WorkflowConfiguration, user, reason: str = "") -> WorkflowConfiguration:
    if not (user and (user.is_superuser or user.groups.filter(name="docai_approvers").exists())):
        raise PermissionDenied("Only members of docai_approvers may approve configurations.")
    before = {"status": wf.status}
    wf.status = CONFIG_STATUS.approved
    wf.approved_by, wf.approved_at, wf.updated_by = user, timezone.now(), user
    wf.save(update_fields=["status", "approved_by", "approved_at", "updated_by", "modified"])
    audit.record(
        user, "workflow.approved", wf, before=before, after={"status": wf.status}, reason=reason
    )
    return wf


def retire_workflow(wf: WorkflowConfiguration, user, reason: str = "") -> WorkflowConfiguration:
    before = {"status": wf.status}
    wf.status = CONFIG_STATUS.retired
    wf.updated_by = user
    wf.save(update_fields=["status", "updated_by", "modified"])
    audit.record(
        user, "workflow.retired", wf, before=before, after={"status": wf.status}, reason=reason
    )
    return wf


def approve_template(tpl: ExtractionTemplate, user, reason: str = "") -> ExtractionTemplate:
    if not (user and (user.is_superuser or user.groups.filter(name="docai_approvers").exists())):
        raise PermissionDenied("Only members of docai_approvers may approve templates.")
    before = {"status": tpl.status}
    tpl.status = CONFIG_STATUS.approved
    tpl.updated_by = user
    tpl.save(update_fields=["status", "updated_by", "modified"])
    audit.record(
        user, "template.approved", tpl, before=before, after={"status": tpl.status}, reason=reason
    )
    return tpl
