"""Human review. The original prediction (raw_value, category, boundaries) is
never modified: corrections land in reviewed_* fields, every action is a
ReviewAction with before/after, and promotion creates versioned ground truth."""
from __future__ import annotations

from django.db import transaction

from docai.exceptions import ValidationFailed
from docai.logging.context import get_trace_id
from docai.models import (
    LABEL_KIND,
    LABEL_STATUS,
    REVIEW_ACTION,
    REVIEW_STATUS,
    ClassificationResult,
    ExtractedField,
    GroundTruthLabel,
    ReviewAction,
    Segment,
)
from docai.validation.normalize import normalize_value

from . import audit
from .dashboard import invalidate_dashboard


def _snapshot_field(f: ExtractedField) -> dict:
    return {"raw_value": f.raw_value, "reviewed_value": f.reviewed_value, "review_status": f.review_status}


@transaction.atomic
def act_on_field(field: ExtractedField, action: str, user, *, value: str | None = None, reason: str = "") -> ReviewAction:
    before = _snapshot_field(field)
    if action == REVIEW_ACTION.accept:
        field.review_status = REVIEW_STATUS.accepted
        field.reviewed_value = field.raw_value
    elif action == REVIEW_ACTION.correct:
        if value is None:
            raise ValidationFailed(errors={"value": "A corrected value is required."})
        field.review_status = REVIEW_STATUS.corrected
        field.reviewed_value = value
    elif action == REVIEW_ACTION.reject:
        field.review_status = REVIEW_STATUS.rejected
    elif action == REVIEW_ACTION.mark_absent:
        field.review_status = REVIEW_STATUS.absent
        field.reviewed_value = None
    elif action == REVIEW_ACTION.note:
        pass
    else:
        raise ValidationFailed(errors={"action": f"'{action}' does not apply to fields."})
    field.updated_by = user
    field.save(update_fields=["review_status", "reviewed_value", "updated_by", "modified"])
    ra = ReviewAction.objects.create(actor=user, action=action, field=field, before=before, after=_snapshot_field(field),
                                     reason=reason, correlation_id=get_trace_id(), created_by=user)
    audit.record(user, f"review.field.{action}", field, before=before, after=ra.after, reason=reason)
    invalidate_dashboard(field.run.project_id)
    return ra


@transaction.atomic
def reclassify(cr: ClassificationResult, user, *, category: str, reason: str = "") -> ReviewAction:
    before = {"category": cr.category, "reviewed_category": cr.reviewed_category, "review_status": cr.review_status}
    cr.reviewed_category, cr.review_status, cr.updated_by = category, REVIEW_STATUS.corrected, user
    cr.save(update_fields=["reviewed_category", "review_status", "updated_by", "modified"])
    ra = ReviewAction.objects.create(actor=user, action=REVIEW_ACTION.reclassify, classification=cr, before=before,
                                     after={"category": cr.category, "reviewed_category": category, "review_status": cr.review_status},
                                     reason=reason, correlation_id=get_trace_id(), created_by=user)
    audit.record(user, "review.reclassify", cr, before=before, after=ra.after, reason=reason)
    invalidate_dashboard(cr.run.project_id)
    return ra


@transaction.atomic
def accept_classification(cr: ClassificationResult, user, reason: str = "") -> ReviewAction:
    before = {"review_status": cr.review_status}
    cr.review_status, cr.reviewed_category, cr.updated_by = REVIEW_STATUS.accepted, cr.category, user
    cr.save(update_fields=["review_status", "reviewed_category", "updated_by", "modified"])
    review_action = ReviewAction.objects.create(
        actor=user,
        action=REVIEW_ACTION.accept,
        classification=cr,
        before=before,
        after={"review_status": cr.review_status},
        reason=reason,
        correlation_id=get_trace_id(),
        created_by=user,
    )
    invalidate_dashboard(cr.run.project_id)
    return review_action


@transaction.atomic
def split_segment(seg: Segment, user, *, at_unit: int, category_second: str | None = None, reason: str = "") -> list[Segment]:
    if not (seg.start_unit < at_unit <= seg.end_unit):
        raise ValidationFailed(errors={"at_unit": "Split point must be inside the segment (after its first unit)."})
    before = {"start": seg.start_unit, "end": seg.end_unit, "category": seg.category}
    later = list(Segment.objects.filter(run=seg.run, document=seg.document, index__gt=seg.index).order_by("-index"))
    for s in later:                       # make room, avoid unique collisions
        s.index += 1; s.save(update_fields=["index"])
    new = Segment.objects.create(run=seg.run, document=seg.document, index=seg.index + 1, start_unit=at_unit, end_unit=seg.end_unit,
                                 category=category_second or seg.category, score=None, method="human",
                                 evidence={"split_from": str(seg.id)}, review_status=REVIEW_STATUS.corrected, created_by=user)
    seg.end_unit, seg.method, seg.review_status, seg.updated_by = at_unit - 1, "human", REVIEW_STATUS.corrected, user
    seg.save(update_fields=["end_unit", "method", "review_status", "updated_by", "modified"])
    ReviewAction.objects.create(actor=user, action=REVIEW_ACTION.split, segment=seg, before=before,
                                after={"first": [seg.start_unit, seg.end_unit], "second": [new.start_unit, new.end_unit]},
                                reason=reason, correlation_id=get_trace_id(), created_by=user)
    audit.record(user, "review.segment.split", seg, before=before, after={"new_segment": str(new.id)}, reason=reason)
    return [seg, new]


@transaction.atomic
def merge_segments(first: Segment, second: Segment, user, reason: str = "") -> Segment:
    if first.document_id != second.document_id or first.run_id != second.run_id or second.index != first.index + 1:
        raise ValidationFailed(errors={"segments": "Only adjacent segments of the same document can be merged."})
    before = {"first": [first.start_unit, first.end_unit], "second": [second.start_unit, second.end_unit]}
    first.end_unit, first.method, first.review_status, first.updated_by = second.end_unit, "human", REVIEW_STATUS.corrected, user
    first.evidence = {**(first.evidence or {}), "merged": str(second.id)}
    first.save(update_fields=["end_unit", "method", "review_status", "updated_by", "evidence", "modified"])
    second_idx = second.index
    second.delete()
    for s in Segment.objects.filter(run=first.run, document=first.document, index__gt=second_idx).order_by("index"):
        s.index -= 1; s.save(update_fields=["index"])
    ReviewAction.objects.create(actor=user, action=REVIEW_ACTION.merge, segment=first, before=before,
                                after={"merged": [first.start_unit, first.end_unit]}, reason=reason,
                                correlation_id=get_trace_id(), created_by=user)
    audit.record(user, "review.segment.merge", first, before=before, reason=reason)
    return first


@transaction.atomic
def promote_field_to_ground_truth(field: ExtractedField, user, reason: str = "") -> GroundTruthLabel:
    """Authorized promotion of an accepted/corrected value to a new GT version."""
    if field.review_status not in (REVIEW_STATUS.accepted, REVIEW_STATUS.corrected, REVIEW_STATUS.absent):
        raise ValidationFailed("Only accepted, corrected, or marked-absent fields can be promoted.")
    span = field.spans.first()
    last = GroundTruthLabel.objects.filter(document=field.document, kind=LABEL_KIND.field, field_name=field.name).order_by("-version").first()
    if last and last.status != LABEL_STATUS.superseded:
        last.status = LABEL_STATUS.superseded; last.save(update_fields=["status", "modified"])
    absent = field.review_status == REVIEW_STATUS.absent
    lb = GroundTruthLabel.objects.create(
        document=field.document, unit=span.unit if span else None, kind=LABEL_KIND.field, field_name=field.name,
        expected_value=None if absent else field.reviewed_value, is_absent=absent,
        normalized_value=None if absent else normalize_value(field.reviewed_value, field.field_type),
        azure_span={"word_ids": span.word_ids, "polygon": span.polygon, "offset_start": span.offset_start,
                    "offset_end": span.offset_end, "cell_range": span.cell_range} if span else {},
        mapping_method=(span.mapping_method if span else "") + "+promoted", match_score=span.match_score if span else None,
        labeler=user, version=(last.version + 1) if last else 1, status=LABEL_STATUS.final, notes=reason,
        promoted_from_field=field, created_by=user)
    ReviewAction.objects.create(actor=user, action=REVIEW_ACTION.promote, field=field, before={"label_version": last.version if last else None},
                                after={"label_id": str(lb.id), "version": lb.version}, reason=reason,
                                correlation_id=get_trace_id(), created_by=user)
    audit.record(user, "review.promote", lb, after={"field": field.name, "version": lb.version}, reason=reason)
    return lb


def history_for_field(field: ExtractedField) -> list[dict]:
    return [{"id": str(a.id), "action": a.action, "actor": a.actor.username if a.actor else None, "at": a.created.isoformat(),
             "before": a.before, "after": a.after, "reason": a.reason}
            for a in field.review_actions.select_related("actor").order_by("created")]
