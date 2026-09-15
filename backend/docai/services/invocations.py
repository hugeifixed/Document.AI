"""Lifecycle helpers for persisted headless-invocation reservations."""

from __future__ import annotations

from django.db.models import Q, QuerySet
from django.utils import timezone

from docai.models import RUN_STATUS, WorkflowInvocation
from docai.models.results import INVOCATION_STATUS

_TERMINAL_RUN_STATUSES = (
    RUN_STATUS.succeeded,
    RUN_STATUS.partial,
    RUN_STATUS.failed,
    RUN_STATUS.cancelled,
)


def expired_cleanup_queryset(*, now=None) -> QuerySet[WorkflowInvocation]:
    """Return expired reservations that cannot still acquire or execute work.

    The predicate uses dates, status strings, and foreign-key nullability only.
    Avoiding JSON lookups keeps cleanup behavior consistent on SQLite and Oracle.
    """
    cutoff = now or timezone.now()
    safe_outcome = Q(run__status__in=_TERMINAL_RUN_STATUSES) | Q(
        status=INVOCATION_STATUS.failed,
        run__isnull=True,
    )
    return WorkflowInvocation.objects.filter(expires_at__lte=cutoff).filter(safe_outcome)


def purge_expired_invocations(*, now=None) -> int:
    """Delete replay state only after its guarantee and operation have ended."""
    deleted, _ = expired_cleanup_queryset(now=now).delete()
    return deleted
