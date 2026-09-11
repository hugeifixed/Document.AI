"""Shared abstract bases. Every concrete model gets a UUID primary key,
created/modified timestamps, and (for auditable entities) created_by /
updated_by. Index and constraint names are explicit and length-guarded for
Oracle's identifier limit; migrations never generate names for us."""

from __future__ import annotations

from typing import ClassVar, Self

from django.conf import settings
from django.db import models
from model_utils.managers import SoftDeletableManager
from model_utils.models import SoftDeletableModel, TimeStampedModel, UUIDModel

ORACLE_MAX_IDENT = 30


def ix(name: str) -> str:
    """Deterministic index/constraint name, guarded for Oracle."""
    if len(name) > ORACLE_MAX_IDENT:
        raise ValueError(f"identifier too long for Oracle: {name} ({len(name)})")
    return name


class AuditedModel(UUIDModel, TimeStampedModel):
    """UUID pk + created/modified + who created/last updated it."""

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        db_comment="User who created the record",
        help_text="User who created this record.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        db_comment="User who last updated the record",
        help_text="User who last updated this record.",
    )

    class Meta:
        abstract = True


class SoftDeletableAuditedModel(AuditedModel, SoftDeletableModel):
    """Auditable model with explicit managers for active and removed rows."""

    # Adopt django-model-utils' announced future ``objects`` behavior now and
    # keep ``available_objects`` as the explicit/default application manager.
    # Redeclaring the managers with Self also preserves the concrete
    # Project/Dataset type through query and creation calls.
    objects: ClassVar[models.Manager[Self]] = models.Manager()  # type: ignore[misc]
    available_objects: ClassVar[models.Manager[Self]] = SoftDeletableManager()  # type: ignore[misc]
    all_objects: ClassVar[models.Manager[Self]] = models.Manager()

    class Meta:
        abstract = True
