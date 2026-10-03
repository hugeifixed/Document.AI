"""Run construction, immutable configuration snapshots, and result persistence.

The lifecycle and internal dispatch adapters live in ``services.run_execution``.
Reprocessing remains idempotent by replacing only one run/document result set.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from docai.adapters.llm.base import get_llm
from docai.exceptions import RunStateError, ValidationFailed
from docai.grounding.provenance import field_locations
from docai.logging.context import get_trace_id, new_trace_id
from docai.models import (
    ARTIFACT_KIND,
    ITEM_STATUS,
    REVIEW_STATUS,
    RUN_STATUS,
    WORKFLOW_TYPES,
    ClassificationResult,
    Dataset,
    Document,
    ExtractedField,
    ProcessingArtifact,
    PromptVersion,
    Run,
    RunItem,
    SchemaVersion,
    Segment,
    SourceSpan,
    WorkflowConfiguration,
)
from docai.schemas.config import (
    CONFIG_SCHEMAS,
    BaseWorkflowConfig,
)
from docai.workflows.base import DocumentResult, WorkflowContext

from . import audit, governance, workflow_snapshots
from .run_progress import snapshot as progress_snapshot

_OUTCOME_TO_STATUS = {
    "auto_accept": REVIEW_STATUS.auto_accepted,
    "human_review": REVIEW_STATUS.needs_review,
    "reject": REVIEW_STATUS.rejected,
}


@transaction.atomic
def create_run(
    project,
    workflow: WorkflowConfiguration,
    dataset: Dataset,
    user=None,
    *,
    name: str = "",
    client_reference: str = "",
    sample_size: int | None = None,
    document_ids: list | None = None,
) -> Run:
    if document_ids is not None and sample_size is not None:
        raise ValidationFailed(
            errors={"document_ids": "Choose documents or set a document limit, not both."}
        )
    docs = Document.objects.filter(dataset=dataset, status__in=Document.RUNNABLE_STATUSES)
    if document_ids is not None:
        document_ids = list(dict.fromkeys(str(value) for value in document_ids))
        if not document_ids:
            raise ValidationFailed(errors={"document_ids": "Choose at least one document."})
        docs = docs.filter(id__in=document_ids)
    docs = docs.order_by("created", "id")
    if sample_size:
        docs = docs[:sample_size]
    selected_ids = list(docs.values_list("id", flat=True))
    if document_ids is not None and len(selected_ids) != len(document_ids):
        raise ValidationFailed(
            errors={
                "document_ids": "Some selected documents are unavailable or no longer eligible in this dataset. Reopen the chooser and update your selection."
            }
        )
    if workflow.workflow_type == WORKFLOW_TYPES.evaluate:
        raise RunStateError("Evaluation is started from the evaluations endpoint, not as a run.")
    cfg_model = cast(
        BaseWorkflowConfig,
        CONFIG_SCHEMAS[workflow.workflow_type].model_validate(workflow.config),
    )
    from .layouts import validate_processing_policy

    validate_processing_policy(
        cfg_model.input_quality, cfg_model.di_analysis, str(settings.DOCAI["LAYOUT_ADAPTER"])
    )
    governance.ensure_default_prompts(user)
    snapshot = workflow_snapshots.capture(workflow)
    prompt_versions = snapshot["prompts"]
    schema_versions = snapshot["schemas"]
    model = getattr(cfg_model, "model", None)
    snapshot["document_ids"] = (
        [str(document_id) for document_id in document_ids] if document_ids else None
    )
    run = Run.objects.create(
        project=project,
        workflow=workflow,
        dataset=dataset,
        name=name,
        client_reference=client_reference,
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
    queued_at = timezone.now()
    items = [
        RunItem(
            run=run,
            document_id=document_id,
            idempotency_key=f"{run.id}:{document_id}"[:64],
            status=ITEM_STATUS.queued,
            processing_progress=progress_snapshot("queued", "queued", now=queued_at),
            progress_updated_at=queued_at,
            correlation_id=run.correlation_id,
            created_by=user,
            updated_by=user,
        )
        for document_id in selected_ids
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


def build_context(
    run: Run,
    *,
    run_item: RunItem | None = None,
    progress: Callable[..., bool] | None = None,
) -> WorkflowContext:
    from .checkpoints import Checkpoints
    from .llm_debug import evidence_debug_capture
    from .llm_usage import observer_for

    resolved = workflow_snapshots.restore(run.config_snapshot)
    llm_key = resolved.llm_adapter_key
    if settings.DOCAI["LLM_ADAPTER"] == "mock" and llm_key != "mock":
        llm_key = "mock"  # environment-level override: local/test never reaches Azure
    params = resolved.parameters

    def provider_retry(stage: str, retry_at) -> None:
        if progress is None:
            return
        operations = {
            "segmentation": "identifying_groups",
            "classification": "classifying",
            "extraction": "extracting",
            "generic_kv": "extracting",
        }
        progress(
            "analyzing",
            "retry_wait" if retry_at is not None else operations.get(stage, "extracting"),
            retry_at=retry_at,
            preserve_scope=True,
            force=True,
        )

    llm = get_llm(
        llm_key,
        deployment=resolved.deployment,
        parameters=params,
        usage_observer=(
            observer_for(run_item) if run_item is not None and llm_key != "mock" else None
        ),
        retry_observer=provider_retry if progress is not None else None,
    )
    checkpoints = (
        Checkpoints(
            run_item,
            provider_identity={
                "adapter": llm_key,
                "deployment": getattr(llm, "deployment", ""),
                "api_version": settings.DOCAI["AZURE_OPENAI_API_VERSION"],
                "endpoint": settings.DOCAI["AZURE_OPENAI_ENDPOINT"],
                "parameters": params,
            },
        )
        if run_item is not None and run_item.attempts
        else None
    )
    ctx = WorkflowContext(
        debug_capture=evidence_debug_capture(run_item),
        checkpoint_invoke=checkpoints.invoke if checkpoints else None,
        checkpoint_discard=checkpoints.discard if checkpoints else None,
        workflow_type=resolved.workflow_type,
        config=resolved.config,
        llm=llm,
        prompts=resolved.prompts,
        layout_adapter_key=resolved.layout_adapter_key,
        progress=progress,
        api_version=settings.DOCAI["AZURE_DI_API_VERSION"]
        if resolved.layout_adapter_key == "azure_di"
        else "",
    )
    if resolved.template:
        ctx.template = resolved.template  # type: ignore[attr-defined]
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
    from .layouts import artifact_for_document, units_for_artifact

    item = RunItem.objects.filter(run=run, document=doc).first()
    artifact = item.layout_artifact if item is not None else artifact_for_document(doc)
    units = {u.index: u for u in units_for_artifact(doc, artifact)}
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
            list_candidates=f.candidates if f.field_type == "list" and f.conflict else [],
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
            grounded=f.field_type != "list" and f.grounding is not None,
            created_by=run.created_by,
        )
        for location in field_locations(f):
            span_values = location.span_values()
            if span_values is None:
                continue
            u = units.get(location.unit_index)
            if u:
                SourceSpan.objects.create(
                    unit=u,
                    field=ef,
                    origin="model",
                    created_by=run.created_by,
                    **span_values,
                )
    if res.raw_responses:
        import json

        from docai.adapters.storage import artifact_path, save_bytes

        payload = json.dumps(
            {
                "run": str(run.id),
                "responses": res.raw_responses,
                "property_evidence": [
                    {
                        "name": f.name,
                        "segment_index": f.segment_index,
                        "properties": f.property_evidence,
                    }
                    for f in res.fields
                    if f.property_evidence
                ],
            },
            ensure_ascii=False,
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
