"""Runs, per-document run items, and results: segments, classifications,
extracted fields, and the source spans that ground every one of them."""

from __future__ import annotations

from django.db import models
from model_utils import Choices, FieldTracker
from model_utils.models import StatusModel

from .base import AuditedModel, ImmutableEventModel, ix
from .catalog import (
    Dataset,
    Project,
    PromptVersion,
    SchemaVersion,
    WorkflowConfiguration,
)
from .documents import Document, SourceUnit

RUN_STATUS = Choices(
    ("queued", "Queued"),
    ("running", "Running"),
    ("succeeded", "Succeeded"),
    ("failed", "Failed"),
    ("cancelled", "Cancelled"),
    ("partial", "Partially succeeded"),
)
ITEM_STATUS = Choices(
    ("queued", "Queued"),
    ("running", "Running"),
    ("succeeded", "Succeeded"),
    ("failed", "Failed"),
    ("skipped", "Skipped"),
)
LLM_USAGE_OUTCOME = Choices(
    ("succeeded", "Succeeded"),
    ("invalid_output", "Invalid output"),
)
LLM_SAFETY_OUTCOME = Choices(
    ("unknown", "Not reported"),
    ("clear", "Clear"),
    ("flagged", "Flagged"),
    ("blocked", "Blocked"),
)
REVIEW_STATUS = Choices(
    ("pending", "Pending"),
    ("auto_accepted", "Auto-accepted"),
    ("needs_review", "Needs review"),
    ("accepted", "Accepted"),
    ("corrected", "Corrected"),
    ("rejected", "Rejected"),
    ("absent", "Marked absent"),
)
VALIDATION_STATUS = Choices(
    ("not_run", "Not run"), ("passed", "Passed"), ("failed", "Failed"), ("warning", "Warning")
)
METHOD = Choices(
    ("llm", "LLM"),
    ("rules", "Deterministic rules"),
    ("segmentation", "Segmentation"),
    ("template", "Template"),
    ("human", "Human"),
)
INVOCATION_STATUS = Choices(
    ("accepting", "Accepting request"),
    ("run_created", "Run created"),
    ("failed", "Failed before run creation"),
)


class WorkflowInvocation(AuditedModel):
    """Idempotency reservation for the headless workflow API.

    The reservation is created before uploads are persisted.  Keeping the
    request hash in a normal character column makes the concurrency check
    identical on SQLite and Oracle; ``failure_errors`` is never filtered or
    compared in SQL.
    """

    workflow = models.ForeignKey(
        WorkflowConfiguration,
        on_delete=models.PROTECT,
        related_name="invocations",
        help_text="Pinned workflow version requested by the caller.",
    )
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.PROTECT,
        related_name="workflow_invocations",
        help_text="Dataset supplied with the invocation.",
    )
    key = models.CharField(max_length=128, help_text="Caller-supplied Idempotency-Key.")
    request_hash = models.CharField(
        max_length=64,
        help_text="SHA-256 of the canonical request identity.",
    )
    status = models.CharField(
        max_length=16,
        choices=INVOCATION_STATUS,
        default=INVOCATION_STATUS.accepting,
        help_text="Reservation state before a run is available.",
    )
    run = models.OneToOneField(
        "docai.Run",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="invocation",
        help_text="Run created by this invocation, when available.",
    )
    failure_status = models.PositiveSmallIntegerField(null=True, blank=True)
    failure_code = models.CharField(max_length=64, blank=True)
    failure_message = models.CharField(max_length=500, blank=True)
    failure_errors = models.JSONField(
        default=list,
        blank=True,
        help_text="Bounded validation details replayed to an identical retry.",
    )

    class Meta:
        db_table = "docai_workflow_invocation"
        ordering = ["-created"]
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "workflow", "key"],
                name=ix("uq_inv_user_wf_key"),
            )
        ]
        indexes = [
            models.Index(fields=["workflow", "created"], name=ix("ix_inv_wf_created")),
            models.Index(fields=["request_hash"], name=ix("ix_inv_request_hash")),
        ]

    def __str__(self):
        return f"{self.workflow_id}:{self.key}"


class Run(StatusModel, AuditedModel):
    STATUS = RUN_STATUS
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="runs",
        db_comment="Project",
        help_text="Project.",
    )
    workflow = models.ForeignKey(
        WorkflowConfiguration,
        on_delete=models.PROTECT,
        related_name="runs",
        db_comment="Workflow configuration",
        help_text="Workflow used.",
    )
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.PROTECT,
        related_name="runs",
        db_comment="Dataset processed",
        help_text="Dataset processed.",
    )
    name = models.CharField(
        max_length=160, blank=True, db_comment="Run label", help_text="Optional label."
    )
    config_snapshot = models.JSONField(
        db_comment="Immutable config copy at start",
        help_text="Exact configuration used; never edited after start.",
    )
    config_hash = models.CharField(
        max_length=71, db_comment="sha256 of snapshot", help_text="Integrity hash."
    )
    prompt_versions = models.JSONField(
        default=dict,
        blank=True,
        db_comment="stage -> prompt name/version",
        help_text="Prompt versions per stage.",
    )
    schema_versions = models.JSONField(
        default=dict,
        blank=True,
        db_comment="stage -> schema name/version",
        help_text="Schema versions per stage.",
    )
    model_deployment = models.CharField(
        max_length=120, blank=True, db_comment="Model deployment", help_text="Deployment."
    )
    model_parameters = models.JSONField(
        default=dict, blank=True, db_comment="Model params", help_text="Params."
    )
    layout_adapter = models.CharField(
        max_length=32, blank=True, db_comment="Layout adapter key", help_text="OCR/layout adapter."
    )
    llm_adapter = models.CharField(
        max_length=32, blank=True, db_comment="LLM adapter key", help_text="LLM adapter."
    )
    sample_size = models.PositiveIntegerField(
        null=True, blank=True, db_comment="Sample limit", help_text="If sampling, N docs."
    )
    stage = models.CharField(
        max_length=32, blank=True, db_comment="Current stage", help_text="Current stage."
    )
    total_items = models.PositiveIntegerField(
        default=0, db_comment="Items to process", help_text="Total documents."
    )
    processed_items = models.PositiveIntegerField(
        default=0, db_comment="Items done", help_text="Processed so far."
    )
    failed_items = models.PositiveIntegerField(
        default=0, db_comment="Items failed", help_text="Failed count."
    )
    started_at = models.DateTimeField(
        null=True, blank=True, db_comment="Start", help_text="Start time."
    )
    finished_at = models.DateTimeField(
        null=True, blank=True, db_comment="End", help_text="End time."
    )
    cancel_requested = models.BooleanField(
        default=False, db_comment="Cancellation flag", help_text="Cancel requested."
    )
    errors = models.JSONField(
        default=list, blank=True, db_comment="Run-level errors", help_text="Sanitized errors."
    )
    warnings = models.JSONField(
        default=list, blank=True, db_comment="Warnings", help_text="Warnings."
    )
    metrics = models.JSONField(
        default=dict,
        blank=True,
        db_comment="Metrics / quality indicators",
        help_text="Evaluation metrics (with GT) or quality indicators (without).",
    )
    correlation_id = models.CharField(
        max_length=32, blank=True, db_comment="Trace id", help_text="Correlation id."
    )
    tracker = FieldTracker(fields=["status", "stage"])

    class Meta:
        db_table = "docai_run"
        db_table_comment = (
            "An execution of a workflow over a dataset with an immutable config snapshot"
        )
        verbose_name = "run"
        verbose_name_plural = "runs"
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["project", "status"], name=ix("ix_docai_run_proj_status")),
            models.Index(fields=["workflow"], name=ix("ix_docai_run_wf")),
            models.Index(fields=["dataset"], name=ix("ix_docai_run_ds")),
            models.Index(fields=["config_hash"], name=ix("ix_docai_run_hash")),
            models.Index(fields=["created"], name=ix("ix_docai_run_created")),
            models.Index(fields=["correlation_id"], name=ix("ix_docai_run_corr")),
        ]

    def __str__(self):
        return self.name or str(self.id)


class RunItem(StatusModel, AuditedModel):
    STATUS = ITEM_STATUS
    run = models.ForeignKey(
        Run, on_delete=models.CASCADE, related_name="items", db_comment="Run", help_text="Run."
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="run_items",
        db_comment="Document",
        help_text="Document processed.",
    )
    layout_artifact = models.ForeignKey(
        "docai.ProcessingArtifact",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
        related_name="run_items",
        help_text="Immutable layout used by this exact execution.",
    )
    input_quality = models.JSONField(
        default=dict,
        blank=True,
        help_text="Scan enhancement summary and recoverable warnings.",
    )
    processing_progress = models.JSONField(
        default=dict,
        blank=True,
        help_text="Latest bounded processing milestone; empty for historical runs.",
    )
    progress_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the latest processing milestone was recorded.",
    )
    idempotency_key = models.CharField(
        max_length=64,
        db_comment="run+document key",
        help_text="Guarantees a retry never double-processes.",
    )
    stage = models.CharField(
        max_length=32, blank=True, db_comment="Current stage", help_text="Stage."
    )
    attempts = models.PositiveIntegerField(
        default=0, db_comment="Attempts", help_text="Attempt count."
    )
    worker_task_id = models.CharField(
        max_length=64,
        blank=True,
        db_comment="Current worker delivery",
        help_text="Celery task id currently responsible for this item.",
    )
    worker_deliveries = models.PositiveSmallIntegerField(
        default=0,
        db_comment="Deliveries for current task",
        help_text="Delivery count for the current Celery task id.",
    )
    error_code = models.CharField(
        max_length=48, blank=True, db_comment="Error code", help_text="Machine code."
    )
    error_message = models.TextField(
        blank=True, db_comment="Sanitized error", help_text="Plain-language error."
    )
    retryable = models.BooleanField(
        default=False, db_comment="Retry-safe flag", help_text="Whether retry may help."
    )
    duration_ms = models.PositiveIntegerField(
        null=True, blank=True, db_comment="Duration", help_text="Processing time."
    )
    correlation_id = models.CharField(
        max_length=32, blank=True, db_comment="Trace id", help_text="Correlation id."
    )

    class Meta:
        db_table = "docai_run_item"
        db_table_comment = "Per-document job state within a run (progress, retries, failures)"
        verbose_name = "run item"
        verbose_name_plural = "run items"
        constraints = [
            models.UniqueConstraint(fields=["run", "document"], name=ix("uq_docai_ri_run_doc"))
        ]
        indexes = [
            models.Index(fields=["run", "status"], name=ix("ix_docai_ri_run_status")),
            models.Index(fields=["idempotency_key"], name=ix("ix_docai_ri_idem")),
        ]


class LLMUsageEvent(ImmutableEventModel):
    """Immutable token accounting for one provider response."""

    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="llm_usage_events",
        db_comment="Run",
        help_text="Run that caused this model call.",
    )
    run_item = models.ForeignKey(
        RunItem,
        on_delete=models.CASCADE,
        related_name="llm_usage_events",
        db_comment="Run item",
        help_text="Per-document job that caused this model call.",
    )
    stage = models.CharField(
        max_length=32,
        db_comment="Workflow stage",
        help_text="Workflow stage, such as classification or extraction.",
    )
    chunk_index = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_comment="Chunk index",
        help_text="Zero-based chunk index when the call processed a chunk.",
    )
    segment_index = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_comment="Segment index",
        help_text="Zero-based segment index when the call processed a segment.",
    )
    attempt = models.PositiveSmallIntegerField(
        default=1,
        db_comment="Item attempt",
        help_text="Run-item attempt during which the provider responded.",
    )
    provider = models.CharField(
        max_length=32,
        db_comment="Provider adapter",
        help_text="Provider adapter that reported usage.",
    )
    model_deployment = models.CharField(
        max_length=120,
        blank=True,
        db_comment="Model deployment",
        help_text="Configured model deployment.",
    )
    model_name = models.CharField(
        max_length=120,
        blank=True,
        db_comment="Provider model",
        help_text="Model identifier reported by the provider.",
    )
    provider_request_id = models.CharField(
        max_length=128,
        blank=True,
        db_comment="Provider request id",
        help_text="Provider response identifier for reconciliation.",
    )
    api_version = models.CharField(
        max_length=32,
        blank=True,
        db_comment="Provider API version",
        help_text="Configured provider API version used for the call.",
    )
    prompt_name = models.CharField(
        max_length=120, blank=True, db_comment="Prompt name", help_text="Prompt name."
    )
    prompt_version = models.PositiveIntegerField(
        null=True, blank=True, db_comment="Prompt version", help_text="Prompt version."
    )
    schema_name = models.CharField(
        max_length=120, blank=True, db_comment="Schema name", help_text="Output schema name."
    )
    schema_version = models.PositiveIntegerField(
        null=True, blank=True, db_comment="Schema version", help_text="Output schema version."
    )
    input_tokens = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        db_comment="Input tokens",
        help_text="Input tokens reported by the provider.",
    )
    cached_input_tokens = models.PositiveBigIntegerField(
        default=0,
        db_comment="Cached input tokens",
        help_text="Cached input tokens included in input_tokens.",
    )
    output_tokens = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        db_comment="Output tokens",
        help_text="Output tokens reported by the provider.",
    )
    reasoning_tokens = models.PositiveBigIntegerField(
        default=0,
        db_comment="Reasoning tokens",
        help_text="Reasoning tokens included in output_tokens.",
    )
    total_tokens = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        db_comment="Total tokens",
        help_text="Total tokens reported by the provider.",
    )
    latency_ms = models.PositiveIntegerField(
        default=0,
        db_comment="Provider latency",
        help_text="End-to-end adapter latency in milliseconds.",
    )
    outcome = models.CharField(
        max_length=24,
        choices=LLM_USAGE_OUTCOME,
        default=LLM_USAGE_OUTCOME.succeeded,
        db_comment="Call outcome",
        help_text="Whether structured output validation succeeded.",
    )
    finish_reason = models.CharField(
        max_length=32,
        blank=True,
        db_comment="Provider finish reason",
        help_text="Provider-reported reason the response ended.",
    )
    safety_outcome = models.CharField(
        max_length=16,
        choices=LLM_SAFETY_OUTCOME,
        default=LLM_SAFETY_OUTCOME.unknown,
        db_comment="Normalized safety outcome",
        help_text="Content-free summary of provider safety signals.",
    )
    correlation_id = models.CharField(
        max_length=32, blank=True, db_comment="Trace id", help_text="Correlation id."
    )

    class Meta:
        db_table = "docai_llm_usage_event"
        db_table_comment = "Per-provider-response token usage without prompt or document content"
        verbose_name = "LLM usage event"
        verbose_name_plural = "LLM usage events"
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["run", "created"], name=ix("ix_docai_llmu_run_created")),
            models.Index(fields=["run_item"], name=ix("ix_docai_llmu_item")),
            models.Index(fields=["run", "stage"], name=ix("ix_docai_llmu_run_stage")),
        ]

    def __str__(self):
        tokens = self.total_tokens if self.total_tokens is not None else "unreported"
        return f"{self.stage}: {tokens} tokens"


class Segment(AuditedModel):
    run = models.ForeignKey(
        Run, on_delete=models.CASCADE, related_name="segments", db_comment="Run", help_text="Run."
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="segments",
        db_comment="Parent document",
        help_text="Parent document.",
    )
    index = models.PositiveIntegerField(
        db_comment="Segment order", help_text="Order within the document."
    )
    start_unit = models.PositiveIntegerField(
        db_comment="First unit index (0-based)", help_text="Start page/sheet."
    )
    end_unit = models.PositiveIntegerField(
        db_comment="Last unit index inclusive", help_text="End page/sheet."
    )
    category = models.CharField(
        max_length=64, db_comment="Category key or 'other'", help_text="Assigned category."
    )
    score = models.FloatField(
        null=True,
        blank=True,
        db_comment="Model score/confidence",
        help_text="A score, not a guarantee.",
    )
    method = models.CharField(
        max_length=16,
        choices=METHOD,
        default=METHOD.llm,
        db_comment="How assigned",
        help_text="Method.",
    )
    evidence = models.JSONField(
        default=dict,
        blank=True,
        db_comment="Evidence + continuation info",
        help_text="Evidence text, continuation_of, source ids.",
    )
    continuation_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        db_comment="Segment this continues",
        help_text="Continuation relationship.",
    )
    review_status = models.CharField(
        max_length=16,
        choices=REVIEW_STATUS,
        default=REVIEW_STATUS.pending,
        db_comment="Review state",
        help_text="Review state.",
    )

    class Meta:
        db_table = "docai_segment"
        db_table_comment = "Logical documents found inside a file (unbundling output)"
        verbose_name = "segment"
        verbose_name_plural = "segments"
        ordering = ["document", "index"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "document", "index"], name=ix("uq_docai_seg_run_doc_idx")
            ),
            models.CheckConstraint(
                condition=models.Q(end_unit__gte=models.F("start_unit")),
                name=ix("ck_docai_seg_range"),
            ),
        ]
        indexes = [
            models.Index(fields=["run", "category"], name=ix("ix_docai_seg_run_cat")),
            models.Index(fields=["review_status"], name=ix("ix_docai_seg_review")),
        ]


class ClassificationResult(AuditedModel):
    run = models.ForeignKey(
        Run,
        on_delete=models.CASCADE,
        related_name="classifications",
        db_comment="Run",
        help_text="Run.",
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="classifications",
        db_comment="Document",
        help_text="Document.",
    )
    segment = models.ForeignKey(
        Segment,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="classifications",
        db_comment="Segment (if unbundled)",
        help_text="Segment, when classifying segments.",
    )
    category = models.CharField(
        max_length=64, db_comment="Category key / other / needs_review", help_text="Category."
    )
    score = models.FloatField(
        null=True, blank=True, db_comment="Score", help_text="Rule or model score."
    )
    method = models.CharField(
        max_length=16, choices=METHOD, db_comment="rules|llm|segmentation", help_text="Method."
    )
    rule_score = models.FloatField(
        null=True, blank=True, db_comment="Deterministic rule score", help_text="Rule score."
    )
    matched_evidence = models.JSONField(
        default=list, blank=True, db_comment="Matched rule evidence", help_text="Matches."
    )
    excluded_evidence = models.JSONField(
        default=list, blank=True, db_comment="Exclusion hits", help_text="Exclusions."
    )
    llm_evidence = models.TextField(
        blank=True, db_comment="LLM evidence text", help_text="Evidence quoted by the model."
    )
    model_deployment = models.CharField(
        max_length=120, blank=True, db_comment="Model", help_text="Deployment."
    )
    prompt_version = models.ForeignKey(
        PromptVersion,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        db_comment="Prompt",
        help_text="Prompt version.",
    )
    schema_version = models.ForeignKey(
        SchemaVersion,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        db_comment="Schema",
        help_text="Schema version.",
    )
    rule_version = models.CharField(
        max_length=64, blank=True, db_comment="Rule set version/hash", help_text="Rules version."
    )
    review_status = models.CharField(
        max_length=16,
        choices=REVIEW_STATUS,
        default=REVIEW_STATUS.pending,
        db_comment="Review state",
        help_text="Review state.",
    )
    reviewed_category = models.CharField(
        max_length=64, blank=True, db_comment="Human category", help_text="Corrected category."
    )

    class Meta:
        db_table = "docai_classification_result"
        db_table_comment = "Classification predictions with rule/LLM evidence and versions"
        verbose_name = "classification result"
        verbose_name_plural = "classification results"
        indexes = [
            models.Index(fields=["run", "category"], name=ix("ix_docai_cls_run_cat")),
            models.Index(fields=["document"], name=ix("ix_docai_cls_doc")),
            models.Index(fields=["review_status"], name=ix("ix_docai_cls_review")),
        ]


class ExtractedField(AuditedModel):
    list_candidates = models.JSONField(
        default=list,
        blank=True,
        help_text="Conflicting list candidates with source references; retained for human review.",
    )
    run = models.ForeignKey(
        Run, on_delete=models.CASCADE, related_name="fields", db_comment="Run", help_text="Run."
    )
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="fields",
        db_comment="Document",
        help_text="Document.",
    )
    segment = models.ForeignKey(
        Segment,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="fields",
        db_comment="Segment",
        help_text="Segment, when unbundled.",
    )
    name = models.CharField(max_length=120, db_comment="Field name", help_text="Schema field name.")
    field_type = models.CharField(
        max_length=24, default="string", db_comment="string|number|date|...", help_text="Type."
    )
    raw_value = models.TextField(
        blank=True,
        null=True,
        db_comment="Value as extracted (verbatim)",
        help_text="Exactly what the model returned. Never modified.",
    )
    normalized_value = models.TextField(
        blank=True,
        null=True,
        db_comment="Normalized value",
        help_text="Normalized form (dates ISO, numbers canonical). Stored separately.",
    )
    score = models.FloatField(
        null=True, blank=True, db_comment="Score", help_text="Confidence/score."
    )
    source_text = models.TextField(
        blank=True, db_comment="Evidence text", help_text="Verbatim evidence quoted by the model."
    )
    method = models.CharField(
        max_length=16, choices=METHOD, default=METHOD.llm, db_comment="Method", help_text="Method."
    )
    strategy = models.CharField(
        max_length=32,
        blank=True,
        db_comment="Chunking strategy used",
        help_text="Selected strategy.",
    )
    fallback_used = models.CharField(
        max_length=64, blank=True, db_comment="Fallback record", help_text="Any fallback, explicit."
    )
    model_deployment = models.CharField(
        max_length=120, blank=True, db_comment="Model", help_text="Deployment."
    )
    prompt_version = models.ForeignKey(
        PromptVersion,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        db_comment="Prompt",
        help_text="Prompt version.",
    )
    schema_version = models.ForeignKey(
        SchemaVersion,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        db_comment="Schema",
        help_text="Schema version.",
    )
    api_version = models.CharField(
        max_length=64, blank=True, db_comment="Service API version", help_text="API version."
    )
    validation_status = models.CharField(
        max_length=12,
        choices=VALIDATION_STATUS,
        default=VALIDATION_STATUS.not_run,
        db_comment="Validation state",
        help_text="Validation outcome.",
    )
    validation_messages = models.JSONField(
        default=list, blank=True, db_comment="Validation messages", help_text="Messages."
    )
    suggested_correction = models.TextField(
        blank=True,
        null=True,
        db_comment="Suggested fix (never applied)",
        help_text="Validator suggestion; never auto-applied.",
    )
    review_status = models.CharField(
        max_length=16,
        choices=REVIEW_STATUS,
        default=REVIEW_STATUS.pending,
        db_comment="Review state",
        help_text="Review state.",
    )
    reviewed_value = models.TextField(
        blank=True, null=True, db_comment="Human value", help_text="Reviewer's value."
    )
    grounded = models.BooleanField(
        default=False, db_comment="Has source span", help_text="Mapped to a source location."
    )

    class Meta:
        db_table = "docai_extracted_field"
        db_table_comment = (
            "Extracted field values with raw/normalized/reviewed values and provenance"
        )
        verbose_name = "extracted field"
        verbose_name_plural = "extracted fields"
        indexes = [
            models.Index(fields=["run", "name"], name=ix("ix_docai_fld_run_name")),
            models.Index(fields=["document"], name=ix("ix_docai_fld_doc")),
            models.Index(fields=["review_status"], name=ix("ix_docai_fld_review")),
            models.Index(fields=["validation_status"], name=ix("ix_docai_fld_valid")),
            models.Index(fields=["run", "review_status"], name=ix("ix_docai_fld_run_review")),
        ]


class SourceSpan(AuditedModel):
    """Where something lives in the source. Exactly one owner. For PDFs:
    unit + text span offsets + polygon + word ids. For spreadsheets: cell range."""

    unit = models.ForeignKey(
        SourceUnit,
        on_delete=models.CASCADE,
        related_name="spans",
        db_comment="Page/sheet",
        help_text="Unit.",
    )
    field = models.ForeignKey(
        ExtractedField,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="spans",
        db_comment="Owning field",
        help_text="Owning extracted field.",
    )
    classification = models.ForeignKey(
        ClassificationResult,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="spans",
        db_comment="Owning classification",
        help_text="Owner.",
    )
    segment = models.ForeignKey(
        Segment,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="spans",
        db_comment="Owning segment",
        help_text="Owner.",
    )
    label = models.ForeignKey(
        "docai.GroundTruthLabel",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="spans",
        db_comment="Owning ground-truth label",
        help_text="Owner.",
    )
    text = models.TextField(blank=True, db_comment="Span text", help_text="Text covered.")
    offset_start = models.IntegerField(
        null=True, blank=True, db_comment="Start offset in unit content", help_text="Start."
    )
    offset_end = models.IntegerField(
        null=True, blank=True, db_comment="End offset", help_text="End."
    )
    polygon = models.JSONField(
        default=list,
        blank=True,
        db_comment="Polygon in unit coords",
        help_text="[x1,y1,...] normalized 0-1.",
    )
    word_ids = models.JSONField(
        default=list, blank=True, db_comment="Layout word/line ids", help_text="Stable ids."
    )
    cell_range = models.CharField(
        max_length=32, blank=True, db_comment="Sheet cell range (A1:B2)", help_text="Cell range."
    )
    mapping_method = models.CharField(
        max_length=32,
        blank=True,
        db_comment="How mapped",
        help_text="exact|digits|fuzzy|geometry|pdfjs|manual.",
    )
    match_score = models.FloatField(
        null=True, blank=True, db_comment="Mapping confidence", help_text="0-1 match score."
    )
    exceptions = models.JSONField(
        default=list, blank=True, db_comment="Mapping caveats", help_text="Why mapping is partial."
    )
    origin = models.CharField(
        max_length=16, default="model", db_comment="model|pdfjs|azure|human", help_text="Origin."
    )

    class Meta:
        db_table = "docai_source_span"
        db_table_comment = (
            "Source locations (span/polygon/cell range) grounding predictions and labels"
        )
        verbose_name = "source span"
        verbose_name_plural = "source spans"
        indexes = [
            models.Index(fields=["unit"], name=ix("ix_docai_span_unit")),
            models.Index(fields=["field"], name=ix("ix_docai_span_field")),
            models.Index(fields=["label"], name=ix("ix_docai_span_label")),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(field__isnull=False)
                    | models.Q(classification__isnull=False)
                    | models.Q(segment__isnull=False)
                    | models.Q(label__isnull=False)
                ),
                name=ix("ck_docai_span_owner"),
            )
        ]


class Evaluation(AuditedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="evaluations",
        db_comment="Project",
        help_text="Project.",
    )
    run = models.ForeignKey(
        Run,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="evaluations",
        db_comment="Evaluated run (optional)",
        help_text="Run whose predictions were evaluated.",
    )
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.PROTECT,
        related_name="evaluations",
        db_comment="Dataset",
        help_text="Dataset.",
    )
    predictions_source = models.CharField(
        max_length=32,
        default="run",
        db_comment="run|upload",
        help_text="Where predictions came from.",
    )
    normalization = models.JSONField(
        default=dict, blank=True, db_comment="Normalization config", help_text="Normalization used."
    )
    metrics = models.JSONField(
        default=dict, blank=True, db_comment="Computed metrics", help_text="Aggregate + granular."
    )
    has_ground_truth = models.BooleanField(
        default=True, db_comment="GT available", help_text="If false, only quality indicators."
    )

    class Meta:
        db_table = "docai_evaluation"
        db_table_comment = "Evaluation results (metrics with GT; quality indicators without)"
        verbose_name = "evaluation"
        verbose_name_plural = "evaluations"
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["project", "created"], name=ix("ix_docai_eval_proj_created"))
        ]
