"""Ground truth, review actions (corrections never overwrite originals), and
the audit trail."""
from __future__ import annotations

from django.conf import settings
from django.db import models
from model_utils import Choices

from .base import AuditedModel, ix
from .documents import Document, SourceUnit
from .results import ClassificationResult, ExtractedField, Segment

LABEL_KIND = Choices(("field", "Field value"), ("category", "Category"), ("segment", "Segment boundary"))
LABEL_STATUS = Choices(("draft", "Draft"), ("final", "Final"), ("superseded", "Superseded"))
REVIEW_ACTION = Choices(("accept", "Accept"), ("correct", "Correct"), ("reject", "Reject"),
                        ("mark_absent", "Mark absent"), ("reclassify", "Reclassify"),
                        ("split", "Split segment"), ("merge", "Merge segments"),
                        ("note", "Add note"), ("promote", "Promote to ground truth"))


class GroundTruthLabel(AuditedModel):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="labels", db_comment="Document", help_text="Document.")
    unit = models.ForeignKey(SourceUnit, null=True, blank=True, on_delete=models.SET_NULL, related_name="labels",
                             db_comment="Page/sheet", help_text="Unit the label is on.")
    segment_start = models.PositiveIntegerField(null=True, blank=True, db_comment="Segment start unit", help_text="For segment/category labels.")
    segment_end = models.PositiveIntegerField(null=True, blank=True, db_comment="Segment end unit", help_text="Inclusive.")
    kind = models.CharField(max_length=12, choices=LABEL_KIND, db_comment="field|category|segment", help_text="Label kind.")
    field_name = models.CharField(max_length=120, blank=True, db_comment="Field name", help_text="For field labels.")
    category = models.CharField(max_length=64, blank=True, db_comment="Category key", help_text="For category/segment labels.")
    expected_value = models.TextField(blank=True, null=True, db_comment="Expected value (verbatim)", help_text="Truth as it appears.")
    normalized_value = models.TextField(blank=True, null=True, db_comment="Normalized expected value", help_text="Normalized truth.")
    is_absent = models.BooleanField(default=False, db_comment="Field truly absent", help_text="True-blank marker.")
    pdfjs_span = models.JSONField(default=dict, blank=True, db_comment="PDF.js-derived selection",
                                  help_text="page, text, rects (PDF user space) from the labeling UI.")
    azure_span = models.JSONField(default=dict, blank=True, db_comment="Reconciled layout span",
                                  help_text="Matched layout word ids/offsets/polygon.")
    mapping_method = models.CharField(max_length=32, blank=True, db_comment="Reconciliation method", help_text="Method.")
    match_score = models.FloatField(null=True, blank=True, db_comment="Reconciliation score", help_text="0-1.")
    mapping_exceptions = models.JSONField(default=list, blank=True, db_comment="Mapping caveats", help_text="Exceptions.")
    cell_range = models.CharField(max_length=32, blank=True, db_comment="Sheet cell range", help_text="For spreadsheets.")
    labeler = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="labels", db_comment="Labeler", help_text="Who labeled.")
    version = models.PositiveIntegerField(default=1, db_comment="Label version", help_text="Versioned; promotions create new versions.")
    status = models.CharField(max_length=12, choices=LABEL_STATUS, default=LABEL_STATUS.draft, db_comment="draft|final|superseded", help_text="Status.")
    notes = models.TextField(blank=True, db_comment="Notes", help_text="Labeler notes.")
    promoted_from_field = models.ForeignKey(ExtractedField, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                            db_comment="Source prediction if promoted", help_text="Prediction this was promoted from.")

    class Meta:
        db_table = "docai_ground_truth_label"
        db_table_comment = "Versioned ground truth with dual (PDF.js + layout) source mapping"
        verbose_name = "ground-truth label"
        verbose_name_plural = "ground-truth labels"
        indexes = [models.Index(fields=["document", "kind"], name=ix("ix_docai_gt_doc_kind")),
                   models.Index(fields=["document", "field_name"], name=ix("ix_docai_gt_doc_field")),
                   models.Index(fields=["status"], name=ix("ix_docai_gt_status")),
                   models.Index(fields=["created"], name=ix("ix_docai_gt_created"))]


class ReviewAction(AuditedModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="review_actions", db_comment="Reviewer", help_text="Who acted.")
    action = models.CharField(max_length=16, choices=REVIEW_ACTION, db_comment="Action", help_text="Action taken.")
    field = models.ForeignKey(ExtractedField, null=True, blank=True, on_delete=models.CASCADE, related_name="review_actions",
                              db_comment="Target field", help_text="Target field.")
    classification = models.ForeignKey(ClassificationResult, null=True, blank=True, on_delete=models.CASCADE,
                                       related_name="review_actions", db_comment="Target classification", help_text="Target.")
    segment = models.ForeignKey(Segment, null=True, blank=True, on_delete=models.CASCADE, related_name="review_actions",
                                db_comment="Target segment", help_text="Target.")
    before = models.JSONField(default=dict, blank=True, db_comment="State before", help_text="Snapshot before the action.")
    after = models.JSONField(default=dict, blank=True, db_comment="State after", help_text="Snapshot after the action.")
    reason = models.TextField(blank=True, db_comment="Reason", help_text="Why.")
    correlation_id = models.CharField(max_length=32, blank=True, db_comment="Trace id", help_text="Correlation id.")

    class Meta:
        db_table = "docai_review_action"
        db_table_comment = "Human review actions; originals are preserved, corrections stored alongside"
        verbose_name = "review action"
        verbose_name_plural = "review actions"
        ordering = ["-created"]
        indexes = [models.Index(fields=["field"], name=ix("ix_docai_rev_field")),
                   models.Index(fields=["actor", "created"], name=ix("ix_docai_rev_actor_created"))]


class AuditEvent(models.Model):
    """Append-only. No updated_by on purpose."""
    id = models.UUIDField(primary_key=True, editable=False, db_comment="Event id")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="audit_events", db_comment="Actor", help_text="Who.")
    action = models.CharField(max_length=64, db_comment="Action verb", help_text="What happened.")
    object_type = models.CharField(max_length=64, db_comment="Object type", help_text="Model name.")
    object_id = models.CharField(max_length=64, db_comment="Object id", help_text="UUID of the object.")
    timestamp = models.DateTimeField(auto_now_add=True, db_comment="When", help_text="When.")
    correlation_id = models.CharField(max_length=32, blank=True, db_comment="Trace id", help_text="Correlation id.")
    before_ref = models.JSONField(default=dict, blank=True, db_comment="Before reference", help_text="Reference/snapshot before.")
    after_ref = models.JSONField(default=dict, blank=True, db_comment="After reference", help_text="Reference/snapshot after.")
    reason = models.TextField(blank=True, db_comment="Reason", help_text="Why.")

    class Meta:
        db_table = "docai_audit_event"
        db_table_comment = "Append-only audit trail of security-relevant and administrative actions"
        verbose_name = "audit event"
        verbose_name_plural = "audit events"
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["object_type", "object_id"], name=ix("ix_docai_audit_obj")),
                   models.Index(fields=["actor", "timestamp"], name=ix("ix_docai_audit_actor_ts")),
                   models.Index(fields=["timestamp"], name=ix("ix_docai_audit_ts")),
                   models.Index(fields=["correlation_id"], name=ix("ix_docai_audit_corr"))]
