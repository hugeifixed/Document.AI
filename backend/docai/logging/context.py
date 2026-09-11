"""Correlation/request id propagated via contextvars so services, tasks and
adapters log the same trace id as the request that started them."""

import contextvars
import uuid

_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("docai_trace_id", default="")


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def set_trace_id(value: str) -> contextvars.Token:
    return _trace_id.set(value)


def get_trace_id() -> str:
    return _trace_id.get() or ""


def reset_trace_id(token: contextvars.Token) -> None:
    _trace_id.reset(token)
