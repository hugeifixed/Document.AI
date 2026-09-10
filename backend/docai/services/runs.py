"""Run orchestration. create_run snapshots + hashes the configuration and
records prompt/schema/model versions; execute_run processes RunItems through
the workflow strategy via the task runner. Each item is idempotent (keyed on
run+document): re-processing deletes and replaces that item's results only.
Cancellation is cooperative between items. Never touches vendor SDKs."""
from __future__ import annotations

import time
import traceback

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from loguru import logger

from docai.adapters.llm.base import get_llm
from docai.exceptions import DocAIError, RunStateError
from docai.logging.context import get_trace_id, new_trace_id, set_trace_id
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
from docai.schemas.config import CONFIG_SCHEMAS
from docai.workflows.base import DocumentResult, PromptRef, WorkflowContext, get_strategy

from . import audit, governance
from .layouts import get_or_build_layout

_OUTCOME_TO_STATUS = {"auto_accept": REVIEW_STATUS.auto_accepted, "human_review": REVIEW_STATUS.needs_review,
                      "reject": REVIEW_STATUS.rejected}


def create_run(project, workflow: WorkflowConfiguration, dataset: Dataset, user=None, *, name: str = "",
               sample_size: int | None = None, document_ids: list | None = None) -> Run:
    if workflow.workflow_type == WORKFLOW_TYPES.evaluate:
        raise RunStateError("Evaluation is started from the evaluations endpoint, not as a run.")
    prompts = governance.ensure_default_prompts(user)
    cfg_model = CONFIG_SCHEMAS[workflow.workflow_type].model_validate(workflow.config)
    prompt_versions = {}
    for stage, pv in prompts.items():
        override = cfg_model.prompt_overrides.get(stage) if hasattr(cfg_model, "prompt_overrides") else None
        if override:
            pv = PromptVersion.objects.filter(name=override).order_by("-version").first() or pv
        prompt_versions[stage] = {"name": pv.name, "version": pv.version, "hash": pv.content_hash}
    schema_versions = {}
    for sc in getattr(cfg_model, "schemas", []) or []:
        schema_versions[sc.name] = {"name": sc.name, "version": sc.version}
    if getattr(cfg_model, "schema_", None):
        schema_versions[cfg_model.schema_.name] = {"name": cfg_model.schema_.name, "version": cfg_model.schema_.version}
    template_snapshot = None
    if workflow.workflow_type == WORKFLOW_TYPES.extract_template:
        tpl = ExtractionTemplate.objects.select_related("schema_version", "prompt_version", "model_config").get(
            project=project, name=cfg_model.template_name, version=cfg_model.template_version)
        template_snapshot = {"name": tpl.name, "version": tpl.version, "document_type": tpl.document_type,
                             "schema": {"name": tpl.schema_version.name, "version": tpl.schema_version.version,
                                        "fields": tpl.schema_version.field_definitions},
                             "field_guidance": tpl.field_guidance, "validations": tpl.validations,
                             "chunking": tpl.chunking, "prompt": {"name": tpl.prompt_version.name, "version": tpl.prompt_version.version},
                             "model": {"deployment": tpl.model_config.deployment, "parameters": tpl.model_config.parameters}}
        prompt_versions["extraction"] = {"name": tpl.prompt_version.name, "version": tpl.prompt_version.version,
                                         "hash": tpl.prompt_version.content_hash}
        schema_versions[tpl.schema_version.name] = {"name": tpl.schema_version.name, "version": tpl.schema_version.version}
    model = getattr(cfg_model, "model", None)
    snapshot = {"workflow": {"id": str(workflow.id), "name": workflow.name, "version": workflow.version,
                             "type": workflow.workflow_type, "hash": workflow.content_hash, "status": workflow.status},
                "config": workflow.config, "prompts": prompt_versions, "schemas": schema_versions,
                "template": template_snapshot,
                "adapters": {"layout": settings.DOCAI["LAYOUT_ADAPTER"], "llm": (model.adapter if model else settings.DOCAI["LLM_ADAPTER"])},
                "platform_version": settings.DOCAI["PLATFORM_VERSION"], "document_ids": document_ids or None}
    run = Run.objects.create(
        project=project, workflow=workflow, dataset=dataset, name=name, config_snapshot=snapshot,
        config_hash=governance.content_hash(snapshot), prompt_versions=prompt_versions, schema_versions=schema_versions,
        model_deployment=(model.deployment if model else ""), model_parameters=(model.model_dump() if model else {}),
        layout_adapter=snapshot["adapters"]["layout"], llm_adapter=snapshot["adapters"]["llm"], sample_size=sample_size,
        status=RUN_STATUS.queued, correlation_id=get_trace_id() or new_trace_id(), created_by=user, updated_by=user)
    docs = Document.objects.filter(dataset=dataset, status__in=[DOC_STATUS.validated, DOC_STATUS.processed, DOC_STATUS.failed])
    if document_ids:
        docs = docs.filter(id__in=document_ids)
    docs = docs.order_by("created")
    if sample_size:
        docs = docs[:sample_size]
    items = [RunItem(run=run, document=d, idempotency_key=f"{run.id}:{d.id}"[:64], status=ITEM_STATUS.queued,
                     correlation_id=run.correlation_id) for d in docs]
    RunItem.objects.bulk_create(items)
    run.total_items = len(items)
    if workflow.status != "approved" and dataset.is_production:
        run.warnings = ["Unapproved configuration executed against a production dataset."]
    run.save(update_fields=["total_items", "warnings", "modified"])
    audit.record(user, "run.created", run, after={"workflow": workflow.name, "version": workflow.version,
                                                    "hash": run.config_hash, "items": len(items)})
    return run


def build_context(run: Run) -> WorkflowContext:
    snap = run.config_snapshot
    wf_type = snap["workflow"]["type"]
    cfg = CONFIG_SCHEMAS[wf_type].model_validate(snap["config"])
    prompts = {}
    for stage, ref in snap["prompts"].items():
        pv = PromptVersion.objects.get(name=ref["name"], version=ref["version"])
        prompts[stage] = PromptRef(name=pv.name, version=pv.version, system=pv.system_prompt, user_template=pv.user_template)
    model = getattr(cfg, "model", None)
    llm_key = snap["adapters"]["llm"]
    if settings.DOCAI["LLM_ADAPTER"] == "mock" and llm_key != "mock":
        llm_key = "mock"   # environment-level override: local/test never reaches Azure
    params = model.model_dump() if model else {}
    llm = get_llm(llm_key, deployment=(snap.get("template") or {}).get("model", {}).get("deployment") or (model.deployment if model else None),
                  parameters=params)
    ctx = WorkflowContext(workflow_type=wf_type, config=cfg, llm=llm, prompts=prompts,
                          layout_adapter_key=snap["adapters"]["layout"],
                          api_version=settings.DOCAI["AZURE_DI_API_VERSION"] if snap["adapters"]["layout"] == "azure_di" else "")
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
    units = {u.index: u for u in SourceUnit.objects.filter(document=doc)}
    seg_objs: dict[int, Segment] = {}
    for s in res.segments:
        seg = Segment.objects.create(run=run, document=doc, index=s.index, start_unit=s.start_unit, end_unit=s.end_unit,
                                     category=s.category, score=s.score, method=s.method,
                                     evidence={**s.evidence, "sources": s.sources},
                                     review_status=_OUTCOME_TO_STATUS.get(s.evidence.get("review", ""), REVIEW_STATUS.pending),
                                     created_by=run.created_by)
        seg_objs[s.index] = seg
        for src in s.sources:
            u = units.get(src.get("unit_index"))
            if u:
                SourceSpan.objects.create(unit=u, segment=seg, text=src.get("quote", "")[:500], word_ids=src.get("ids", []),
                                          mapping_method="model", match_score=None, origin="model", created_by=run.created_by)
    for si, s in seg_objs.items():
        src = next((x for x in res.segments if x.index == si), None)
        if src and src.continuation_of is not None and src.continuation_of in seg_objs:
            s.continuation_of = seg_objs[src.continuation_of]; s.save(update_fields=["continuation_of"])
    for c in res.classifications:
        cr = ClassificationResult.objects.create(
            run=run, document=doc, segment=seg_objs.get(c.segment_index) if c.segment_index is not None else None,
            category=c.category, score=c.score, method=c.method, rule_score=c.rule_score,
            matched_evidence=c.matched_evidence, excluded_evidence=c.excluded_evidence, llm_evidence=c.llm_evidence,
            model_deployment=c.model_deployment, prompt_version=_prompt_obj(c.prompt), schema_version=_schema_obj(c.schema),
            rule_version=c.rule_version, review_status=_OUTCOME_TO_STATUS.get(c.review_outcome, REVIEW_STATUS.pending),
            created_by=run.created_by)
        for src in c.sources:
            u = units.get(src.get("unit_index"))
            if u:
                SourceSpan.objects.create(unit=u, classification=cr, text=str(src.get("quote", ""))[:500],
                                          word_ids=src.get("ids", []), mapping_method="model", origin="model",
                                          created_by=run.created_by)
    for f in res.fields:
        ef = ExtractedField.objects.create(
            run=run, document=doc, segment=seg_objs.get(f.segment_index) if f.segment_index is not None else None,
            name=f.name[:120], field_type=f.field_type, raw_value=f.raw_value, normalized_value=f.normalized_value,
            score=f.score, source_text=(f.source_text or "")[:2000], method=f.method, strategy=f.strategy,
            fallback_used=f.fallback_used[:64], model_deployment=f.model_deployment, prompt_version=_prompt_obj(f.prompt),
            schema_version=_schema_obj(f.schema), api_version=f.api_version, validation_status=f.validation_status,
            validation_messages=f.validation_messages, suggested_correction=f.suggested_correction,
            review_status=_OUTCOME_TO_STATUS.get(f.review_outcome, REVIEW_STATUS.pending), grounded=f.grounding is not None,
            created_by=run.created_by)
        if f.grounding:
            u = units.get(f.grounding.get("unit_index"))
            if u:
                SourceSpan.objects.create(unit=u, field=ef, text=(f.raw_value or "")[:500],
                                          offset_start=f.grounding.get("offset_start"), offset_end=f.grounding.get("offset_end"),
                                          polygon=f.grounding.get("polygon", []), word_ids=f.grounding.get("word_ids", []),
                                          cell_range=f.grounding.get("cell_range", "") or "", mapping_method=f.grounding.get("method", ""),
                                          match_score=f.grounding.get("score"), origin="model", created_by=run.created_by)
    if res.raw_responses:
        import json

        from docai.adapters.storage import artifact_path, save_bytes
        payload = json.dumps({"run": str(run.id), "responses": res.raw_responses}, ensure_ascii=False).encode("utf-8")
        rel = artifact_path(str(doc.id), "raw_model_response", f"run-{str(run.id)[:8]}.json")
        stored, digest = save_bytes(rel, payload)
        ProcessingArtifact.objects.create(document=doc, kind=ARTIFACT_KIND.raw_model_response, stage=run.workflow.workflow_type,
                                          storage_path=stored, sha256=digest, size_bytes=len(payload), service_name=run.llm_adapter,
                                          parameters={"run_id": str(run.id), "retention_days": settings.DOCAI["RAW_MODEL_RESPONSE_RETENTION_DAYS"]},
                                          created_by=run.created_by)


def process_item(item_id) -> str:
    """Idempotent, retry-safe unit of work (what a Celery task would call)."""
    item = RunItem.objects.select_related("run", "document", "run__workflow").get(id=item_id)
    run, doc = item.run, item.document
    token = set_trace_id(item.correlation_id or run.correlation_id or new_trace_id())
    t0 = time.perf_counter()
    if run.cancel_requested:
        item.status = ITEM_STATUS.skipped; item.save(update_fields=["status", "status_changed", "modified"])
        return item.status
    item.status, item.attempts, item.stage = ITEM_STATUS.running, item.attempts + 1, "layout"
    item.error_code = item.error_message = ""
    item.save(update_fields=["status", "attempts", "stage", "error_code", "error_message", "status_changed", "modified"])
    Document.objects.filter(pk=doc.pk).update(status=DOC_STATUS.processing)
    try:
        layout = get_or_build_layout(doc, run.layout_adapter)
        item.stage = "workflow"; item.save(update_fields=["stage"])
        ctx = build_context(run)
        strategy = get_strategy(ctx.workflow_type)
        res = strategy.process_document(ctx, layout)
        item.stage = "persist"; item.save(update_fields=["stage"])
        persist_result(run, doc, res, layout)
        item.status, item.stage = ITEM_STATUS.succeeded, "done"
        item.duration_ms = int((time.perf_counter() - t0) * 1000)
        item.save(update_fields=["status", "stage", "duration_ms", "status_changed", "modified"])
        Document.objects.filter(pk=doc.pk).update(status=DOC_STATUS.processed)
        if res.warnings:
            Run.objects.filter(pk=run.pk).update(warnings=list(run.warnings or []) + [f"{doc.original_filename}: {w}" for w in res.warnings][:200])
        logger.bind(run_id=str(run.id), document_id=str(doc.id), stage="done", duration_ms=item.duration_ms,
                    fields=len(res.fields), segments=len(res.segments)).info("item processed")
    except DocAIError as exc:
        _fail(item, exc.error_code, exc.message, exc.retryable, t0)
    except Exception as exc:  # noqa: BLE001
        logger.bind(run_id=str(run.id), document_id=str(doc.id), stage=item.stage).error(
            "item failed: {}", type(exc).__name__)
        logger.debug(traceback.format_exc())
        _fail(item, "INTERNAL_ERROR", "Processing failed unexpectedly. Reference the trace id when reporting.", True, t0)
    finally:
        try:
            from docai.logging.context import reset_trace_id
            reset_trace_id(token)
        except ValueError:
            pass
    return item.status


def _fail(item, code, message, retryable, t0):
    item.status, item.error_code, item.error_message, item.retryable = ITEM_STATUS.failed, code, message[:2000], retryable
    item.duration_ms = int((time.perf_counter() - t0) * 1000)
    item.save(update_fields=["status", "error_code", "error_message", "retryable", "duration_ms", "status_changed", "modified"])
    Document.objects.filter(pk=item.document_id).update(status=DOC_STATUS.failed)


def execute_run(run_id, only_failed: bool = False) -> Run:
    """Drive all items through the configured task runner, then finalize."""
    from docai.tasks.runner import get_runner
    run = Run.objects.get(id=run_id)
    if run.status in (RUN_STATUS.succeeded, RUN_STATUS.cancelled) and not only_failed:
        raise RunStateError()
    run.status, run.started_at, run.stage = RUN_STATUS.running, run.started_at or timezone.now(), "processing"
    run.cancel_requested = False
    run.save(update_fields=["status", "started_at", "stage", "cancel_requested", "status_changed", "modified"])
    qs = run.items.filter(status=ITEM_STATUS.failed) if only_failed else run.items.exclude(status=ITEM_STATUS.succeeded)
    ids = list(qs.values_list("id", flat=True))
    runner = get_runner()
    scheduled = runner.map(process_item, ids, run_id=str(run.id))
    if runner.is_async and scheduled:
        run.refresh_from_db()
        return run
    return finalize_run(run.id)


def finalize_run(run_id) -> Run:
    run = Run.objects.get(id=run_id)
    counts = {s: run.items.filter(status=s).count() for s in (ITEM_STATUS.succeeded, ITEM_STATUS.failed, ITEM_STATUS.skipped, ITEM_STATUS.queued)}
    run.processed_items = counts[ITEM_STATUS.succeeded] + counts[ITEM_STATUS.failed]
    run.failed_items = counts[ITEM_STATUS.failed]
    if run.cancel_requested:
        run.status = RUN_STATUS.cancelled
    elif counts[ITEM_STATUS.failed] and counts[ITEM_STATUS.succeeded]:
        run.status = RUN_STATUS.partial
    elif counts[ITEM_STATUS.failed]:
        run.status = RUN_STATUS.failed
    else:
        run.status = RUN_STATUS.succeeded
    run.finished_at, run.stage = timezone.now(), "finalized"
    from .evaluation import metrics_for_run
    try:
        run.metrics = metrics_for_run(run)
    except Exception as exc:  # noqa: BLE001
        logger.bind(run_id=str(run.id)).warning("metrics failed: {}", type(exc).__name__)
        run.metrics = {"error": "metrics could not be computed"}
    run.save(update_fields=["processed_items", "failed_items", "status", "finished_at", "stage", "metrics", "status_changed", "modified"])
    audit.record(run.created_by, "run.finished", run, after={"status": run.status, "processed": run.processed_items,
                                                              "failed": run.failed_items})
    return run


def request_cancel(run: Run, user=None) -> Run:
    if run.status not in (RUN_STATUS.queued, RUN_STATUS.running):
        raise RunStateError()
    run.cancel_requested = True; run.updated_by = user
    run.save(update_fields=["cancel_requested", "updated_by", "modified"])
    audit.record(user, "run.cancel_requested", run)
    return run


def progress(run: Run) -> dict:
    items = run.items.values_list("status", flat=True)
    from collections import Counter
    c = Counter(items)
    done = c[ITEM_STATUS.succeeded] + c[ITEM_STATUS.failed] + c[ITEM_STATUS.skipped]
    est = None
    if run.started_at and done and run.total_items > done and run.status == RUN_STATUS.running:
        elapsed = (timezone.now() - run.started_at).total_seconds()
        est = round(elapsed / done * (run.total_items - done))
    return {"total": run.total_items, "succeeded": c[ITEM_STATUS.succeeded], "failed": c[ITEM_STATUS.failed],
            "skipped": c[ITEM_STATUS.skipped], "queued": c[ITEM_STATUS.queued], "running": c[ITEM_STATUS.running],
            "remaining": run.total_items - done, "stage": run.stage, "estimated_seconds_remaining": est}
