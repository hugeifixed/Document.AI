"""Allocate truth versions and supersede applicable semantics without deleting geometry."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils import timezone

from docai.models import LABEL_STATUS, Document, GroundTruthLabel, SourceUnit


def next_truth_version(
    document: Document,
    *,
    kind: str,
    field_name: str = "",
    unit: SourceUnit | None = None,
    is_absent: bool = False,
    scope: dict[str, Any] | None = None,
) -> int:
    """Called inside capture/promotion transactions with a document allocation lock.

    Absence is document-wide. New geometry replaces the same representation and
    global truth; other representations keep their historical geometric labels.
    Versions remain document-wide so evaluation can select the latest semantics.
    """
    Document.objects.select_for_update().only("pk").get(pk=document.pk)
    labels = GroundTruthLabel.objects.filter(document=document, kind=kind, field_name=field_name)
    labels = labels.filter(**(scope or {}))
    latest = labels.order_by("-version").values_list("version", flat=True).first() or 0
    if unit is not None and not is_absent:
        labels = labels.filter(
            Q(unit__layout_artifact_id=unit.layout_artifact_id)
            | Q(unit__isnull=True)
            | Q(is_absent=True)
        )
    labels.exclude(status=LABEL_STATUS.superseded).update(
        status=LABEL_STATUS.superseded, modified=timezone.now()
    )
    return latest + 1
