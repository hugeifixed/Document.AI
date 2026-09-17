"""Private execution checkpoints; only scalar identities participate in queries."""

from django.db import models

from .base import AuditedModel, ix


class ProcessingCheckpoint(AuditedModel):
    """Resume compatible provider work within one run item without repeating completed calls."""

    run_item = models.ForeignKey(
        "RunItem",
        on_delete=models.CASCADE,
        related_name="checkpoints",
        db_comment="Owning run item",
        help_text="Document-processing item whose attempts may reuse this checkpoint.",
    )
    kind = models.CharField(
        max_length=16,
        db_comment="di_operation|llm_output",
        help_text="Checkpoint type: a resumable Document Intelligence operation or validated LLM output.",
    )
    fingerprint = models.CharField(
        max_length=64,
        db_comment="SHA-256 of effective processing inputs",
        help_text="Identifies compatible inputs and configuration; unique per run item and checkpoint type.",
    )
    metadata = models.JSONField(
        default=dict,
        db_comment="Private provider-operation recovery state",
        help_text="Saved operation reference and resubmission state; empty for LLM-output checkpoints.",
    )
    artifact = models.ForeignKey(
        "ProcessingArtifact",
        null=True,
        on_delete=models.CASCADE,
        related_name="checkpoints",
        db_comment="Private validated-output artifact",
        help_text="Stored LLM result used for replay; absent for Document Intelligence operation checkpoints.",
    )

    class Meta:
        db_table = "docai_processing_checkpoint"
        db_table_comment = (
            "Private per-run-item checkpoints for provider recovery and validated output reuse"
        )
        constraints = [
            models.UniqueConstraint(
                fields=["run_item", "kind", "fingerprint"], name=ix("uq_docai_checkpoint")
            )
        ]
