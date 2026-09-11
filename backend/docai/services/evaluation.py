"""Evaluation: joins a run's predictions to final ground-truth labels and
computes documented metrics; without labels it computes quality indicators
only. Accepts uploaded predictions too (predictions_source='upload')."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from docai.evaluation.metrics import (
    aggregate_segmentation,
    classification_metrics,
    extraction_metrics,
    quality_indicators,
    segmentation_metrics,
)
from docai.models import (
    LABEL_KIND,
    LABEL_STATUS,
    ClassificationResult,
    Evaluation,
    ExtractedField,
    GroundTruthLabel,
    Run,
    Segment,
)
from docai.schemas.config import CONFIG_SCHEMAS

from . import audit


def _field_specs(run: Run) -> dict[str, dict[str, Any]]:
    snap = run.config_snapshot
    cfg = CONFIG_SCHEMAS[snap["workflow"]["type"]](**snap["config"])
    specs: dict[str, dict[str, Any]] = {}
    for sc in getattr(cfg, "schemas", []) or []:
        for f in sc.fields:
            specs[f.name] = {"type": f.type, "match_mode": f.match_mode, "required": f.required}
    sc = getattr(cfg, "schema_", None)
    if sc:
        for f in sc.fields:
            specs[f.name] = {"type": f.type, "match_mode": f.match_mode, "required": f.required}
    tpl = snap.get("template")
    if tpl:
        for f in tpl["schema"]["fields"]:
            specs[f["name"]] = {
                "type": f.get("type", "string"),
                "match_mode": f.get("match_mode", "auto"),
                "required": f.get("required", False),
            }
    return specs


def _labels(run: Run):
    doc_ids = list(run.items.values_list("document_id", flat=True))
    return GroundTruthLabel.objects.filter(document_id__in=doc_ids, status=LABEL_STATUS.final)


def metrics_for_run(
    run: Run,
    normalization: dict[str, Any] | None = None,
    numeric_tolerance: float = 0.01,
    prediction_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    labels = list(_labels(run))
    specs = _field_specs(run)
    fields = list(
        ExtractedField.objects.filter(run=run).values(
            "document_id",
            "name",
            "raw_value",
            "normalized_value",
            "score",
            "grounded",
            "validation_status",
            "segment_id",
        )
    )
    result: dict[str, Any] = {
        "documents": run.total_items,
        "processed": run.processed_items,
        "failed": run.failed_items,
    }
    if not labels:
        result["quality_indicators"] = quality_indicators(
            [
                {
                    "doc": str(f["document_id"]),
                    "name": f["name"],
                    "value": f["raw_value"],
                    "score": f["score"],
                    "grounded": f["grounded"],
                    "validation_status": f["validation_status"],
                }
                for f in fields
            ],
            required={n for n, s in specs.items() if s.get("required")},
        )
        result["has_ground_truth"] = False
        return result
    result["has_ground_truth"] = True

    # ---- extraction: (doc, field) join; docs with any field label are graded
    field_truth: dict[tuple, str | None] = {}
    labeled_docs = set()
    for lb in labels:
        if lb.kind == LABEL_KIND.field:
            field_truth[(lb.document_id, lb.field_name)] = (
                None if lb.is_absent else (lb.expected_value or "")
            )
            labeled_docs.add(lb.document_id)
    preds: dict[tuple, str | None] = {}
    for f in fields:
        key = (f["document_id"], f["name"])
        if key not in preds or (f["raw_value"] not in (None, "") and preds[key] in (None, "")):
            preds[key] = f["raw_value"]
    rows: list[dict[str, Any]] = []
    for (doc_id, name), truth in field_truth.items():
        rows.append(
            {"doc": str(doc_id), "field": name, "truth": truth, "pred": preds.get((doc_id, name))}
        )
    # predictions for labeled docs on fields with no label at all are ungraded (not spurious): noted
    if rows:
        result["extraction"] = extraction_metrics(rows, specs, normalization, numeric_tolerance)
        result["extraction"]["graded_documents"] = len(labeled_docs)

    # ---- classification: category labels vs run classifications (document-level)
    cat_truth = {
        lb.document_id: lb.category
        for lb in labels
        if lb.kind == LABEL_KIND.category and lb.segment_start is None
    }
    if cat_truth:
        pred_cat: dict[Any, str] = {}
        for classified in ClassificationResult.objects.filter(run=run, segment__isnull=True).values(
            "document_id", "category", "score"
        ):
            pred_cat[classified["document_id"]] = classified["category"]
        # unbundle runs: use the first segment's category for document-level labels
        for segment_classification in (
            ClassificationResult.objects.filter(run=run, segment__isnull=False)
            .order_by("segment__index")
            .values("document_id", "category")
        ):
            pred_cat.setdefault(
                segment_classification["document_id"], segment_classification["category"]
            )
        classification_pairs = [(t, pred_cat.get(d, "other")) for d, t in cat_truth.items()]
        result["classification"] = classification_metrics(classification_pairs)

    # ---- segmentation: page-range labels vs run segments
    seg_truth: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for lb in labels:
        if lb.kind in (LABEL_KIND.segment, LABEL_KIND.category) and lb.segment_start is not None:
            seg_truth[lb.document_id].append(
                {
                    "start": lb.segment_start,
                    "end": lb.segment_end if lb.segment_end is not None else lb.segment_start,
                    "category": lb.category or "other",
                }
            )
    if seg_truth:
        seg_pred: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for s in Segment.objects.filter(run=run).values(
            "document_id", "start_unit", "end_unit", "category"
        ):
            seg_pred[s["document_id"]].append(
                {"start": s["start_unit"], "end": s["end_unit"], "category": s["category"]}
            )
        per_doc: list[dict[str, Any]] = []
        units = {
            i.document_id: max(i.document.page_count, i.document.sheet_count, 1)
            for i in run.items.select_related("document")
        }
        for doc_id, truth_segments in seg_truth.items():
            per_doc.append(
                segmentation_metrics(truth_segments, seg_pred.get(doc_id, []), units.get(doc_id, 1))
            )
        result["segmentation"] = {
            "aggregate": aggregate_segmentation(per_doc),
            "per_document": per_doc,
        }
        # page-level classification pairs from segments
        segment_pairs: list[tuple[str, str]] = []
        for doc_id, truth_segments in seg_truth.items():
            preds_d = seg_pred.get(doc_id, [])
            for t in truth_segments:
                hit = next((p for p in preds_d if p["start"] <= t["start"] <= p["end"]), None)
                segment_pairs.append((t["category"], hit["category"] if hit else "other"))
        if segment_pairs and "classification" not in result:
            result["classification"] = classification_metrics(segment_pairs)
    return result


def create_evaluation(
    run: Run, user=None, normalization: dict | None = None, numeric_tolerance: float = 0.01
) -> Evaluation:
    metrics = metrics_for_run(run, normalization, numeric_tolerance)
    ev = Evaluation.objects.create(
        project=run.project,
        run=run,
        dataset=run.dataset,
        predictions_source="run",
        normalization=normalization or {},
        metrics=metrics,
        has_ground_truth=metrics.get("has_ground_truth", False),
        created_by=user,
    )
    audit.record(
        user, "evaluation.created", ev, after={"run": str(run.id), "has_gt": ev.has_ground_truth}
    )
    return ev
