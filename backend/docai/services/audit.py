import uuid

from docai.logging.context import get_trace_id
from docai.models import AuditEvent


def record(actor, action: str, obj, *, before: dict | None = None, after: dict | None = None, reason: str = "") -> AuditEvent:
    return AuditEvent.objects.create(
        id=uuid.uuid4(), actor=actor if getattr(actor, "pk", None) else None, action=action,
        object_type=type(obj).__name__ if not isinstance(obj, str) else obj,
        object_id=str(getattr(obj, "pk", obj)), correlation_id=get_trace_id(),
        before_ref=before or {}, after_ref=after or {}, reason=reason or "")
