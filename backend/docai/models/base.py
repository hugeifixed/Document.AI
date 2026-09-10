"""Shared abstract bases. Every concrete model gets a UUID primary key,
created/modified timestamps, and (for auditable entities) created_by /
updated_by. Index and constraint names are explicit and length-guarded for
Oracle's identifier limit; migrations never generate names for us."""
from __future__ import annotations

from django.conf import settings
from django.db import models
from model_utils.models import SoftDeletableModel, TimeStampedModel, UUIDModel

ORACLE_MAX_IDENT = 30


def ix(name: str) -> str:
    """Deterministic index/constraint name, guarded for Oracle."""
    assert len(name) <= ORACLE_MAX_IDENT, f"identifier too long for Oracle: {name} ({len(name)})"
    return name


class AuditedModel(UUIDModel, TimeStampedModel):
    """UUID pk + created/modified + who created/last updated it."""
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", db_comment="User who created the record",
        help_text="User who created this record.")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", db_comment="User who last updated the record",
        help_text="User who last updated this record.")

    class Meta:
        abstract = True


class SoftDeletableAuditedModel(AuditedModel, SoftDeletableModel):
    """Auditable + soft delete (is_removed). Default manager hides removed rows."""

    class Meta:
        abstract = True
