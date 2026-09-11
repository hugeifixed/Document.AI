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
    ModelConfiguration,
    Project,
    PromptVersion,
    SchemaVersion,
    WorkflowConfiguration,
)
from docai.schemas.config import validate_workflow_config
from docai.workflows.prompts import DEFAULTS

from . import audit


def _lock_project(project: Project) -> None:
    """Serialize version allocation for every project-scoped configuration."""
    Project.available_objects.select_for_update().only("pk").get(pk=project.pk)


def _next_version(queryset) -> int:
    last = queryset.order_by("-version").only("version").first()
    return last.version + 1 if last else 1


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
    _lock_project(project)
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


@transaction.atomic
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


@transaction.atomic
def new_prompt_version(
    name: str, purpose: str, system_prompt: str, user_template: str, user=None
) -> PromptVersion:
    versions = PromptVersion.objects.select_for_update().filter(name=name)
    pv = PromptVersion.objects.create(
        name=name,
        version=_next_version(versions),
        purpose=purpose,
        system_prompt=system_prompt,
        user_template=user_template,
        content_hash=content_hash([system_prompt, user_template]),
        created_by=user,
    )
    audit.record(user, "prompt.version_created", pv, after={"name": name, "version": pv.version})
    return pv


@transaction.atomic
def new_schema_version(name: str, field_definitions: list[dict], user=None) -> SchemaVersion:
    from docai.schemas.config import ExtractionSchemaConfig, FieldSpec

    versions = SchemaVersion.objects.select_for_update().filter(name=name)
    version = _next_version(versions)
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


def validate_workflow(workflow_type: str, config: dict) -> dict:
    """Validate and normalize a workflow configuration at the governance seam."""
    try:
        return validate_workflow_config(workflow_type, config)
    except ValueError as exc:
        raise WorkflowConfigError(errors={"config": str(exc)[:500]}) from None


@transaction.atomic
def create_model_version(
    *,
    name: str,
    adapter: str,
    deployment: str,
    parameters: dict | None = None,
    user=None,
) -> ModelConfiguration:
    """Create the next immutable model configuration revision."""
    versions = ModelConfiguration.objects.select_for_update().filter(name=name)
    model = ModelConfiguration.objects.create(
        name=name,
        version=_next_version(versions),
        adapter=adapter,
        deployment=deployment,
        parameters=parameters or {},
        created_by=user,
        updated_by=user,
    )
    audit.record(
        user, "model.version_created", model, after={"name": name, "version": model.version}
    )
    return model


@transaction.atomic
def create_template_version(
    *,
    project: Project,
    name: str,
    user=None,
    **values,
) -> ExtractionTemplate:
    """Create the next immutable template revision under the project lock."""
    _lock_project(project)
    versions = ExtractionTemplate.objects.filter(project=project, name=name)
    template = ExtractionTemplate.objects.create(
        project=project,
        name=name,
        version=_next_version(versions),
        created_by=user,
        updated_by=user,
        **values,
    )
    audit.record(
        user,
        "template.version_created",
        template,
        after={"name": name, "version": template.version},
    )
    return template


@transaction.atomic
def create_workflow_version(
    project, name: str, workflow_type: str, config: dict, user=None
) -> WorkflowConfiguration:
    validated = validate_workflow(workflow_type, config)
    _lock_project(project)
    versions = WorkflowConfiguration.objects.filter(project=project, name=name)
    wf = WorkflowConfiguration.objects.create(
        project=project,
        name=name,
        version=_next_version(versions),
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
