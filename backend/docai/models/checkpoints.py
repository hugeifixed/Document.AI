"""Private execution checkpoints; only scalar identities participate in queries."""

from django.db import models

from .base import AuditedModel, ix


class ProcessingCheckpoint(AuditedModel):
    run_item = models.ForeignKey("RunItem", on_delete=models.CASCADE, related_name="checkpoints")
    kind = models.CharField(max_length=16)
    fingerprint = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict)
    artifact = models.ForeignKey(
        "ProcessingArtifact", null=True, on_delete=models.CASCADE, related_name="checkpoints"
    )

    class Meta:
        db_table = "docai_processing_checkpoint"
        constraints = [
            models.UniqueConstraint(
                fields=["run_item", "kind", "fingerprint"], name=ix("uq_docai_checkpoint")
            )
        ]
