"""Run construction, immutable configuration snapshots, and result persistence.

The lifecycle and internal dispatch adapters live in ``services.run_execution``.
Reprocessing remains idempotent by replacing only one run/document result set.
"""

from __future__ import annotations

from typing import cast

from django.conf import settings
from django.db import transaction

from docai.adapters.llm.base import get_llm
from docai.exceptions import RunStateError
from docai.logging.context import get_trace_id, new_trace_id
from docai.models import (
    ARTIFACT_KIND,
    DOC_STATUS,
    ITEM_STATUS,
    REVIEW_STATUS,
    RUN_STATUS,
    WORKFLOW_TYPES,
    ClassificationResult,
    Dataset,
    Document,
    ExtractedField,
    ExtractionTemplate,
    ProcessingArtifact,
    PromptVersion,
    Run,
    RunItem,
    SchemaVersion,
    Segment,
    SourceSpan,
    SourceUnit,
    WorkflowConfiguration,
)
from docai.schemas.config import (
    CONFIG_SCHEMAS,
    BaseWorkflowConfig,
    ExtractStructuredConfig,
    ExtractTemplateConfig,
    ExtractUnstructuredConfig,
)
from docai.workflows.base import DocumentResult, PromptRef, WorkflowContext

from . import audit, governance
from .dashboard import invalidate_dashboard

_OUTCOME_TO_STATUS = {
    "auto_accept": REVIEW_STATUS.auto_accepted,
    "human_review": REVIEW_STATUS.needs_review,
    "reject": REVIEW_STATUS.rejected,
}


def create_run(
    project,
    workflow: WorkflowConfiguration,
    dataset: Dataset,
    user=None,
    *,
    name: str = "",
    sample_size: int | None = None,
    document_ids: list | None = None,
) -> Run:
    if workflow.workflow_type == WORKFLOW_TYPES.evaluate:
        raise RunStateError("Evaluation is started from the evaluations endpoint, not as a run.")
    prompts = governance.ensure_default_prompts(user)
    cfg_model = cast(
        BaseWorkflowConfig,
        CONFIG_SCHEMAS[workflow.workflow_type].model_validate(workflow.config),
    )
    prompt_versions = {}
    for stage, pv in prompts.items():
        override = (
            cfg_model.prompt_overrides.get(stage)
            if hasattr(cfg_model, "prompt_overrides")
            else None
        )
        if override:
            pv = PromptVersion.objects.filter(name=override).order_by("-version").first() or pv
        prompt_versions[stage] = {"name": pv.name, "version": pv.version, "hash": pv.content_hash}
    schema_versions = {}
    for sc in getattr(cfg_model, "schemas", []) or []:
        schema_versions[sc.name] = {"name": sc.name, "version": sc.version}
    schema_config = (
        cfg_model.schema_
        if isinstance(cfg_model, (ExtractStructuredConfig, ExtractUnstructuredConfig))
        else None
    )
    if schema_config is not None:
        schema_versions[schema_config.name] = {
            "name": schema_config.name,
            "version": schema_config.version,
        }
    template_snapshot = None
    if workflow.workflow_type == WORKFLOW_TYPES.extract_template:
        if not isinstance(cfg_model, ExtractTemplateConfig):
            raise RunStateError("The extraction-template configuration is invalid.")
        tpl = ExtractionTemplate.objects.select_related(
            "schema_version", "prompt_version", "model_config"
        ).get(project=project, name=cfg_model.template_name, version=cfg_model.template_version)
        template_snapshot = {
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
        prompt_versions["extraction"] = {
            "name": tpl.prompt_version.name,
            "version": tpl.prompt_version.version,
            "hash": tpl.prompt_version.content_hash,
        }
        schema_versions[tpl.schema_version.name] = {
            "name": tpl.schema_version.name,
            "version": tpl.schema_version.version,
        }
    model = getattr(cfg_model, "model", None)
    snapshot = {
        "workflow": {
            "id": str(workflow.id),
            "name": workflow.name,
            "version": workflow.version,
            "type": workflow.workflow_type,
            "hash": workflow.content_hash,
            "status": workflow.status,
        },
        "config": workflow.config,
        "prompts": prompt_versions,
        "schemas": schema_versions,
        "template": template_snapshot,
        "adapters": {
            "layout": settings.DOCAI["LAYOUT_ADAPTER"],
            "llm": (model.adapter if model else settings.DOCAI["LLM_ADAPTER"]),
        },
        "platform_version": settings.DOCAI["PLATFORM_VERSION"],
        "document_ids": [str(document_id) for document_id in document_ids]
        if document_ids
        else None,
    }
    run = Run.objects.create(
        project=project,
        workflow=workflow,
        dataset=dataset,
        name=name,
        config_snapshot=snapshot,
        config_hash=governance.content_hash(snapshot),
        prompt_versions=prompt_versions,
        schema_versions=schema_versions,
        model_deployment=(model.deployment if model else ""),
        model_parameters=(model.model_dump() if model else {}),
        layout_adapter=snapshot["adapters"]["layout"],
        llm_adapter=snapshot["adapters"]["llm"],
        sample_size=sample_size,
        status=RUN_STATUS.queued,
        correlation_id=get_trace_id() or new_trace_id(),
        created_by=user,
        updated_by=user,
    )
    docs = Document.objects.filter(
        dataset=dataset, status__in=[DOC_STATUS.validated, DOC_STATUS.processed, DOC_STATUS.failed]
    )
    if document_ids:
        docs = docs.filter(id__in=document_ids)
    docs = docs.order_by("created")
    if sample_size:
        docs = docs[:sample_size]
    items = [
        RunItem(
            run=run,
            document=d,
            idempotency_key=f"{run.id}:{d.id}"[:64],
            status=ITEM_STATUS.queued,
            correlation_id=run.correlation_id,
        )
        for d in docs
    ]
    RunItem.objects.bulk_create(items)
    run.total_items = len(items)
    if workflow.status != "approved" and dataset.is_production:
        run.warnings = ["Unapproved configuration executed against a production dataset."]
    run.save(update_fields=["total_items", "warnings", "modified"])
    audit.record(
        user,
        "run.created",
        run,
        after={
            "workflow": workflow.name,
            "version": workflow.version,
            "hash": run.config_hash,
            "items": len(items),
        },
    )
    return run


def build_context(run: Run) -> WorkflowContext:
    snap = run.config_snapshot
    wf_type = snap["workflow"]["type"]
    cfg = CONFIG_SCHEMAS[wf_type].model_validate(snap["config"])
    prompts = {}
    for stage, ref in snap["prompts"].items():
        pv = PromptVersion.objects.get(name=ref["name"], version=ref["version"])
        prompts[stage] = PromptRef(
            name=pv.name,
            version=pv.version,
            system=pv.system_prompt,
            user_template=pv.user_template,
        )
    model = getattr(cfg, "model", None)
    llm_key = snap["adapters"]["llm"]
    if settings.DOCAI["LLM_ADAPTER"] == "mock" and llm_key != "mock":
        llm_key = "mock"  # environment-level override: local/test never reaches Azure
    params = model.model_dump() if model else {}
    llm = get_llm(
        llm_key,
        deployment=(snap.get("template") or {}).get("model", {}).get("deployment")
        or (model.deployment if model else None),
        parameters=params,
    )
    ctx = WorkflowContext(
        workflow_type=wf_type,
        config=cfg,
        llm=llm,
        prompts=prompts,
        layout_adapter_key=snap["adapters"]["layout"],
        api_version=settings.DOCAI["AZURE_DI_API_VERSION"]
        if snap["adapters"]["layout"] == "azure_di"
        else "",
    )
    if snap.get("template"):
        ctx.template = snap["template"]  # type: ignore[attr-defined]
        if snap["template"].get("chunking"):
            from docai.schemas.config import ChunkingConfig

            ctx.config.chunking = ChunkingConfig.model_validate(snap["template"]["chunking"])
    return ctx


def _prompt_obj(ref):
    if not ref:
        return None
    return PromptVersion.objects.filter(name=ref[0], version=ref[1]).first()


def _schema_obj(ref):
    if not ref:
        return None
    return SchemaVersion.objects.filter(name=ref[0], version=ref[1]).first()


@transaction.atomic
def persist_result(run: Run, doc: Document, res: DocumentResult, layout) -> None:
    """Replace this document's results within the run (idempotent)."""
    Segment.objects.filter(run=run, document=doc).delete()
    ClassificationResult.objects.filter(run=run, document=doc).delete()
    ExtractedField.objects.filter(run=run, document=doc).delete()
    ProcessingArtifact.objects.filter(
        document=doc,
        kind=ARTIFACT_KIND.raw_model_response,
        parameters__run_id=str(run.id),
    ).delete()
    units = {u.index: u for u in SourceUnit.objects.filter(document=doc)}
    seg_objs: dict[int, Segment] = {}
    for segment_result in res.segments:
        seg = Segment.objects.create(
            run=run,
            document=doc,
            index=segment_result.index,
            start_unit=segment_result.start_unit,
            end_unit=segment_result.end_unit,
            category=segment_result.category,
            score=segment_result.score,
            method=segment_result.method,
            evidence={**segment_result.evidence, "sources": segment_result.sources},
            review_status=_OUTCOME_TO_STATUS.get(
                segment_result.evidence.get("review", ""), REVIEW_STATUS.pending
            ),
            created_by=run.created_by,
        )
        seg_objs[segment_result.index] = seg
        for src in segment_result.sources:
            unit_index = src.get("unit_index")
            u = units.get(unit_index) if isinstance(unit_index, int) else None
            if u:
                SourceSpan.objects.create(
                    unit=u,
                    segment=seg,
                    text=src.get("quote", "")[:500],
                    word_ids=src.get("ids", []),
                    mapping_method="model",
                    match_score=None,
                    origin="model",
                    created_by=run.created_by,
                )
    for si, segment_obj in seg_objs.items():
        continuation_source = next((x for x in res.segments if x.index == si), None)
        if (
            continuation_source
            and continuation_source.continuation_of is not None
            and continuation_source.continuation_of in seg_objs
        ):
            segment_obj.continuation_of = seg_objs[continuation_source.continuation_of]
            segment_obj.save(update_fields=["continuation_of"])
    for c in res.classifications:
        cr = ClassificationResult.objects.create(
            run=run,
            document=doc,
            segment=seg_objs.get(c.segment_index) if c.segment_index is not None else None,
            category=c.category,
            score=c.score,
            method=c.method,
            rule_score=c.rule_score,
            matched_evidence=c.matched_evidence,
            excluded_evidence=c.excluded_evidence,
            llm_evidence=c.llm_evidence,
            model_deployment=c.model_deployment,
            prompt_version=_prompt_obj(c.prompt),
            schema_version=_schema_obj(c.schema),
            rule_version=c.rule_version,
            review_status=_OUTCOME_TO_STATUS.get(c.review_outcome, REVIEW_STATUS.pending),
            created_by=run.created_by,
        )
        for src in c.sources:
            unit_index = src.get("unit_index")
            u = units.get(unit_index) if isinstance(unit_index, int) else None
            if u:
                SourceSpan.objects.create(
                    unit=u,
                    classification=cr,
                    text=str(src.get("quote", ""))[:500],
                    word_ids=src.get("ids", []),
                    mapping_method="model",
                    origin="model",
                    created_by=run.created_by,
                )
    for f in res.fields:
        ef = ExtractedField.objects.create(
            run=run,
            document=doc,
            segment=seg_objs.get(f.segment_index) if f.segment_index is not None else None,
            name=f.name[:120],
            field_type=f.field_type,
            raw_value=f.raw_value,
            normalized_value=f.normalized_value,
            score=f.score,
            source_text=(f.source_text or "")[:2000],
            method=f.method,
            strategy=f.strategy,
            fallback_used=f.fallback_used[:64],
            model_deployment=f.model_deployment,
            prompt_version=_prompt_obj(f.prompt),
            schema_version=_schema_obj(f.schema),
            api_version=f.api_version,
            validation_status=f.validation_status,
            validation_messages=f.validation_messages,
            suggested_correction=f.suggested_correction,
            review_status=_OUTCOME_TO_STATUS.get(f.review_outcome, REVIEW_STATUS.pending),
            grounded=f.grounding is not None,
            created_by=run.created_by,
        )
        if f.grounding:
            unit_index = f.grounding.get("unit_index")
            u = units.get(unit_index) if isinstance(unit_index, int) else None
            if u:
                SourceSpan.objects.create(
                    unit=u,
                    field=ef,
                    text=(f.raw_value or "")[:500],
                    offset_start=f.grounding.get("offset_start"),
                    offset_end=f.grounding.get("offset_end"),
                    polygon=f.grounding.get("polygon", []),
                    word_ids=f.grounding.get("word_ids", []),
                    cell_range=f.grounding.get("cell_range", "") or "",
                    mapping_method=f.grounding.get("method", ""),
                    match_score=f.grounding.get("score"),
                    origin="model",
                    created_by=run.created_by,
                )
    if res.raw_responses:
        import json

        from docai.adapters.storage import artifact_path, save_bytes

        payload = json.dumps(
            {"run": str(run.id), "responses": res.raw_responses}, ensure_ascii=False
        ).encode("utf-8")
        rel = artifact_path(str(doc.id), "raw_model_response", f"run-{str(run.id)[:8]}.json")
        stored, digest = save_bytes(rel, payload)
        ProcessingArtifact.objects.create(
            document=doc,
            kind=ARTIFACT_KIND.raw_model_response,
            stage=run.workflow.workflow_type,
            storage_path=stored,
            sha256=digest,
            size_bytes=len(payload),
            service_name=run.llm_adapter,
            parameters={
                "run_id": str(run.id),
                "retention_days": settings.DOCAI["RAW_MODEL_RESPONSE_RETENTION_DAYS"],
            },
            created_by=run.created_by,
        )
    invalidate_dashboard(run.project_id)
