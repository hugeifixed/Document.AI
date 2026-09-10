import time
from contextlib import suppress

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from loguru import logger

from .context import new_trace_id, reset_trace_id, set_trace_id

_QUIET_PATHS = {"/admin/jsi18n/", "/favicon.ico"}
_QUIET_PREFIXES = ("/health/", "/static/")


class CorrelationIdMiddleware(MiddlewareMixin):
    HEADER = "HTTP_X_REQUEST_ID"

    def process_request(self, request):
        incoming = request.META.get(self.HEADER, "")
        trace = incoming[:32] if incoming and incoming.isalnum() else new_trace_id()
        request.docai_trace_token = set_trace_id(trace)
        request.docai_trace_id = trace

    def process_response(self, request, response):
        trace = getattr(request, "docai_trace_id", "")
        if trace:
            response["X-Request-ID"] = trace
        token = getattr(request, "docai_trace_token", None)
        if token is not None:
            with suppress(ValueError):
                reset_trace_id(token)
        return response


def _request_level(method: str, path: str, status: int, duration_ms: float) -> str:
    if status >= 500:
        return "ERROR"
    if status >= 400 or duration_ms >= settings.DOCAI_SLOW_REQUEST_MS:
        return "WARNING"
    quiet = method in {"GET", "HEAD"} and (
        path in _QUIET_PATHS or any(path.startswith(prefix) for prefix in _QUIET_PREFIXES)
    )
    return "DEBUG" if quiet else "INFO"


class RequestLoggingMiddleware(MiddlewareMixin):
    def process_request(self, request):
        request._docai_t0 = time.perf_counter()

    def process_exception(self, request, exception):
        request._docai_exception_type = type(exception).__name__

    def process_response(self, request, response):
        duration_ms = (
            time.perf_counter() - getattr(request, "_docai_t0", time.perf_counter())
        ) * 1000
        duration_ms = round(max(duration_ms, 0), 1)
        user = getattr(getattr(request, "user", None), "id", None)
        match = getattr(request, "resolver_match", None)
        route = (
            getattr(match, "view_name", None) or getattr(match, "route", None)
            if match
            else None
        )
        status = response.status_code
        method = request.method
        path = request.path
        logger.bind(
            event="http_request",
            method=method,
            path=path,
            route=route,
            status=status,
            duration_ms=duration_ms,
            user_id=str(user) if user else None,
            exception_type=getattr(request, "_docai_exception_type", None),
        ).log(
            _request_level(method, path, status, duration_ms),
            f"{method} {path} {status} {duration_ms:.1f}ms",
        )
        return response
