"""Evaluation metrics. Extraction uses the per-field outcome taxonomy from the
prototype — match / mismatch / missing (FN) / spurious (FP) / true_blank (TN) —
which yields precision, recall, F1, and (because TN is real) specificity and
NPV. Classification: multiclass confusion matrix with per-class and macro/
micro/weighted aggregates. Segmentation: boundary P/R/F1, exact match,
page-level accuracy, over/under-splitting. Without ground truth we compute
QUALITY INDICATORS only, and never call them accuracy."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from docai.validation.normalize import values_match


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------
def field_outcome(truth, pred, field_type="string", match_mode="auto", cfg=None, tol=0.01) -> str:
    t_blank, p_blank = truth in (None, ""), pred in (None, "")
    if t_blank and p_blank:
        return "true_blank"
    if t_blank:
        return "spurious"  # hallucinated
    if p_blank:
        return "missing"
    return "match" if values_match(truth, pred, field_type, match_mode, cfg, tol) else "mismatch"


def _safe_div(n, d):
    return round(n / d, 4) if d else None


def extraction_metrics(
    rows: list[dict],
    field_specs: dict[str, dict],
    normalization: dict | None = None,
    numeric_tolerance: float = 0.01,
) -> dict:
    """rows: [{"field": name, "truth": ..., "pred": ..., "doc": id}] — one per (doc, field)."""
    per: dict[str, Counter] = defaultdict(Counter)
    abs_err: dict[str, list[float]] = defaultdict(list)
    out_of_schema: Counter = Counter()
    for r in rows:
        if field_specs and r["field"] not in field_specs:
            out_of_schema[r["field"]] += (
                1  # labeled, but no configured field produces it: reported, not graded
            )
            continue
        spec = field_specs.get(r["field"], {})
        oc = field_outcome(
            r.get("truth"),
            r.get("pred"),
            spec.get("type", "string"),
            spec.get("match_mode", "auto"),
            normalization,
            numeric_tolerance,
        )
        per[r["field"]][oc] += 1
        if (
            spec.get("type") in ("currency", "number", "integer", "percent")
            and r.get("truth") not in (None, "")
            and r.get("pred") not in (None, "")
        ):
            try:
                import re

                a = float(re.sub(r"[^\d.\-]", "", str(r["truth"])))
                b = float(re.sub(r"[^\d.\-]", "", str(r["pred"])))
                abs_err[r["field"]].append(abs(a - b))
            except ValueError:
                pass

    def summarize(c: Counter[str], errs: list[float] | None = None) -> dict[str, Any]:
        tp, fp, fn, tn, mm = c["match"], c["spurious"], c["missing"], c["true_blank"], c["mismatch"]
        graded = tp + fp + fn + tn + mm
        pred_nonblank = tp + fp + mm
        truth_nonblank = tp + fn + mm
        out: dict[str, Any] = {
            "support": graded,
            "match": tp,
            "mismatch": mm,
            "missing": fn,
            "spurious": fp,
            "true_blank": tn,
            "accuracy": _safe_div(tp + tn, graded),
            "precision": _safe_div(tp, pred_nonblank),  # PPV
            "recall": _safe_div(tp, truth_nonblank),  # sensitivity
            "specificity": _safe_div(tn, tn + fp),
            "npv": _safe_div(tn, tn + fn + 0) if (tn + fn) else None,
            "missing_rate": _safe_div(fn, truth_nonblank),
            "hallucinated_rate": _safe_div(fp, pred_nonblank),
            "correct_null_rate": _safe_div(tn, tn + fp),
        }
        p, r = out["precision"], out["recall"]
        out["f1"] = round(2 * p * r / (p + r), 4) if p and r else (0.0 if graded else None)
        if errs:
            out["numeric_mae"] = round(sum(errs) / len(errs), 4)
        return out

    per_field = {f: summarize(c, abs_err.get(f)) for f, c in per.items()}
    total: Counter[str] = Counter()
    for c in per.values():
        total.update(c)
    return {
        "aggregate": summarize(total),
        "per_field": per_field,
        "confusion_taxonomy": ["match", "mismatch", "missing", "spurious", "true_blank"],
        "out_of_schema_labels": dict(out_of_schema),
    }


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------
def classification_metrics(
    pairs: list[tuple[str, str]], other_labels=("other", "needs_review")
) -> dict:
    """pairs: [(truth, pred)] normalized lowercase."""
    pairs = [(str(t).strip().lower(), str(p).strip().lower()) for t, p in pairs if t]
    labels = sorted({t for t, _ in pairs} | {p for _, p in pairs})
    idx = {l: i for i, l in enumerate(labels)}
    m = [[0] * len(labels) for _ in labels]
    for t, p in pairs:
        m[idx[t]][idx[p]] += 1
    n = len(pairs)
    correct = sum(m[i][i] for i in range(len(labels)))
    per_class = {}
    tp_sum = fp_sum = fn_sum = 0
    for l in labels:
        i = idx[l]
        tp = m[i][i]
        fp = sum(m[j][i] for j in range(len(labels)) if j != i)
        fn = sum(m[i][j] for j in range(len(labels)) if j != i)
        tn = n - tp - fp - fn
        support = sum(m[i])
        p, r = _safe_div(tp, tp + fp), _safe_div(tp, tp + fn)
        per_class[l] = {
            "support": support,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": p,
            "recall": r,
            "specificity": _safe_div(tn, tn + fp),
            "npv": _safe_div(tn, tn + fn),
            "f1": round(2 * p * r / (p + r), 4) if p and r else (0.0 if support else None),
        }
        tp_sum += tp
        fp_sum += fp
        fn_sum += fn
    present = [l for l in labels if per_class[l]["support"]]

    def avg(key):
        vals = [per_class[l][key] for l in present if per_class[l][key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    w_total = sum(per_class[l]["support"] for l in present)

    def wavg(key):
        vals = [(per_class[l][key] or 0) * per_class[l]["support"] for l in present]
        return round(sum(vals) / w_total, 4) if w_total else None

    micro_p = _safe_div(tp_sum, tp_sum + fp_sum)
    micro_r = _safe_div(tp_sum, tp_sum + fn_sum)
    other_rate = _safe_div(sum(1 for _, p in pairs if p in other_labels), n)
    return {
        "labels": labels,
        "matrix": m,
        "support": n,
        "accuracy": _safe_div(correct, n),
        "per_class": per_class,
        "macro": {"precision": avg("precision"), "recall": avg("recall"), "f1": avg("f1")},
        "micro": {
            "precision": micro_p,
            "recall": micro_r,
            "f1": round(2 * micro_p * micro_r / (micro_p + micro_r), 4)
            if micro_p and micro_r
            else None,
        },
        "weighted": {"precision": wavg("precision"), "recall": wavg("recall"), "f1": wavg("f1")},
        "false_positives": fp_sum,
        "false_negatives": fn_sum,
        "other_or_unclassified_rate": other_rate,
    }


# --------------------------------------------------------------------------
# segmentation
# --------------------------------------------------------------------------
def segmentation_metrics(truth: list[dict], pred: list[dict], n_units: int) -> dict:
    """Both lists: [{"start": int, "end": int, "category": str}] for ONE document.
    Boundaries = set of unit indexes where a new segment starts (excluding 0)."""
    tb = {s["start"] for s in truth if s["start"] > 0}
    pb = {s["start"] for s in pred if s["start"] > 0}
    tp = len(tb & pb)
    fp = len(pb - tb)
    fn = len(tb - pb)
    p, r = (
        _safe_div(tp, tp + fp) if (tp + fp) else 1.0,
        _safe_div(tp, tp + fn) if (tp + fn) else 1.0,
    )
    exact = sorted((s["start"], s["end"], s["category"].lower()) for s in truth) == sorted(
        (s["start"], s["end"], s["category"].lower()) for s in pred
    )

    def page_cats(segs):
        out = ["" for _ in range(n_units)]
        for s in segs:
            for u in range(s["start"], min(s["end"], n_units - 1) + 1):
                out[u] = s["category"].lower()
        return out

    tc, pc = page_cats(truth), page_cats(pred)
    page_acc = _safe_div(sum(1 for a, b in zip(tc, pc, strict=True) if a == b), n_units)
    return {
        "boundary_precision": p,
        "boundary_recall": r,
        "boundary_f1": round(2 * p * r / (p + r), 4) if p and r else 0.0,
        "exact_segment_match": exact,
        "page_level_category_accuracy": page_acc,
        "over_split": max(0, len(pred) - len(truth)),
        "under_split": max(0, len(truth) - len(pred)),
        "incorrect_split_boundaries": fp,
        "incorrect_merge_boundaries": fn,
        "truth_segments": len(truth),
        "pred_segments": len(pred),
    }


def aggregate_segmentation(per_doc: list[dict]) -> dict:
    if not per_doc:
        return {}
    keys = ["boundary_precision", "boundary_recall", "boundary_f1", "page_level_category_accuracy"]
    agg = {k: round(sum((d[k] or 0) for d in per_doc) / len(per_doc), 4) for k in keys}
    agg["exact_segment_match_rate"] = _safe_div(
        sum(1 for d in per_doc if d["exact_segment_match"]), len(per_doc)
    )
    agg["over_split_docs"] = sum(1 for d in per_doc if d["over_split"])
    agg["under_split_docs"] = sum(1 for d in per_doc if d["under_split"])
    agg["document_count"] = len(per_doc)
    return agg


# --------------------------------------------------------------------------
# quality indicators (no ground truth) — NOT accuracy
# --------------------------------------------------------------------------
def quality_indicators(
    fields: list[dict[str, Any]], required: set[str], low_threshold: float = 0.8
) -> dict[str, Any]:
    """fields: [{"doc": id, "name": n, "value": v, "score": s, "grounded": bool,
    "validation_status": st}]"""
    by_name: dict[str, list[dict]] = defaultdict(list)
    for f in fields:
        by_name[f["name"]].append(f)
    docs = {f["doc"] for f in fields}
    out: dict[str, Any] = {
        "kind": "quality_indicators",
        "note": "No ground truth: these are indicators, not accuracy.",
        "document_count": len(docs),
        "per_field": {},
    }
    for name, items in by_name.items():
        scores = [i["score"] for i in items if i.get("score") is not None]
        hist = Counter(min(int((s or 0) * 10), 9) for s in scores)
        out["per_field"][name] = {
            "count": len(items),
            "non_blank_rate": _safe_div(
                sum(1 for i in items if i.get("value") not in (None, "")), len(items)
            ),
            "required_omission_rate": _safe_div(
                sum(1 for i in items if i.get("value") in (None, "")), len(items)
            )
            if name in required
            else None,
            "low_score_rate": _safe_div(sum(1 for s in scores if s < low_threshold), len(scores))
            if scores
            else None,
            "score_histogram": {
                f"{k / 10:.1f}-{(k + 1) / 10:.1f}": v for k, v in sorted(hist.items())
            },
            "grounding_rate": _safe_div(sum(1 for i in items if i.get("grounded")), len(items)),
            "validation_failure_rate": _safe_div(
                sum(1 for i in items if i.get("validation_status") == "failed"), len(items)
            ),
        }
    return out
