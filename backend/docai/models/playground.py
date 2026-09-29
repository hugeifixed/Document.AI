"""Short-lived workflow proposals; no sample bytes or prompts live in database rows."""

from django.db import models
from django.utils import timezone

from .base import ImmutableEventModel, ix
from .catalog import Project
from .documents import Document


class PlaygroundSession(ImmutableEventModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        db_comment="Owning project",
        help_text="Project used for document access.",
    )
    expires_at = models.DateTimeField(
        db_index=True,
        db_comment="Expiry instant",
        help_text="Session and temporary samples are removed after this instant.",
    )
    last_activity_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        db_comment="Last playground activity",
        help_text="Most recent sample, proposal, or generation-stage change for resume ordering.",
    )
    status = models.CharField(
        max_length=20,
        default="ready",
        db_comment="Generation state",
        help_text="Ready, queued, analyzing, generating, complete, or failed.",
    )
    state_changed_at = models.DateTimeField(
        null=True,
        db_comment="Last generation-stage change",
        help_text="Used to detect a worker that stopped before recording a terminal state.",
    )
    generation_attempt = models.UUIDField(
        null=True,
        editable=False,
        db_comment="Current generation attempt",
        help_text="Fences delayed workers so only the current generation attempt can update this session.",
    )
    goal = models.TextField(
        blank=True,
        db_comment="Operator's requested outcome",
        help_text="Short workflow goal; do not put document contents here.",
    )
    workflow_type = models.CharField(
        max_length=40,
        blank=True,
        db_comment="Proposed workflow type",
        help_text="One of the three supported playground workflow types.",
    )
    proposal = models.JSONField(
        default=dict,
        db_comment="Editable proposal metadata",
        help_text="Fields and source labels without sample values.",
    )
    error_code = models.CharField(
        max_length=40,
        blank=True,
        db_comment="Failure category",
        help_text="Stable machine-readable generation failure code.",
    )
    error_message = models.CharField(
        max_length=500,
        blank=True,
        db_comment="Safe failure explanation",
        help_text="Operator-facing error without source content.",
    )

    class Meta:
        db_table = "docai_playground_session"
        db_table_comment = "Temporary guided workflow proposal owned by one operator"
        indexes = [models.Index(fields=["created_by", "expires_at"], name=ix("ix_pg_owner_expiry"))]


class PlaygroundSample(ImmutableEventModel):
    session = models.ForeignKey(
        PlaygroundSession,
        on_delete=models.CASCADE,
        related_name="samples",
        db_comment="Playground session",
        help_text="Session using this sample.",
    )
    document = models.ForeignKey(
        Document,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        db_comment="Existing dataset document",
        help_text="Reference to an existing document; no copy is made.",
    )
    storage_path = models.CharField(
        max_length=255,
        blank=True,
        db_comment="Temporary source path",
        help_text="Private application storage path for a new upload.",
    )
    filename = models.CharField(
        max_length=255, db_comment="Display filename", help_text="Original filename for the sample."
    )
    file_format = models.CharField(
        max_length=8, db_comment="Detected format", help_text="Normalized source format."
    )
    size_bytes = models.BigIntegerField(
        db_comment="Source byte count", help_text="Used to enforce total sample limits."
    )
    unit_count = models.PositiveIntegerField(
        db_comment="Pages or sheets", help_text="Expected pages or sheets for completeness checks."
    )

    class Meta:
        db_table = "docai_playground_sample"
        db_table_comment = "Temporary upload or reference to an existing dataset document"
        indexes = [models.Index(fields=["session"], name=ix("ix_pg_sample_session"))]


class PlaygroundUsageEvent(ImmutableEventModel):
    session = models.ForeignKey(
        PlaygroundSession,
        null=True,
        on_delete=models.SET_NULL,
        related_name="usage_events",
        db_comment="Playground session",
        help_text="Session making this model call, if it has not expired or been deleted.",
    )
    project_id_snapshot = models.UUIDField(
        db_comment="Project at call time",
        help_text="Keeps project-level usage attributable after the short-lived session expires.",
    )
    stage = models.CharField(
        max_length=24, db_comment="Call stage", help_text="Generate or refine."
    )
    deployment = models.CharField(
        max_length=120,
        blank=True,
        db_comment="Model deployment",
        help_text="Deployment used for the call.",
    )
    input_tokens = models.PositiveIntegerField(
        null=True, db_comment="Input tokens", help_text="Provider-reported input tokens."
    )
    cached_input_tokens = models.PositiveIntegerField(
        default=0,
        db_comment="Cached input tokens",
        help_text="Provider-reported cache-read tokens.",
    )
    output_tokens = models.PositiveIntegerField(
        null=True, db_comment="Output tokens", help_text="Provider-reported output tokens."
    )
    outcome = models.CharField(
        max_length=24, db_comment="Call outcome", help_text="Provider-reported outcome."
    )

    class Meta:
        db_table = "docai_playground_usage"
        db_table_comment = "Content-free token usage for playground model calls"
        indexes = [models.Index(fields=["session", "created"], name=ix("ix_pg_usage_session"))]
