"""Global DRF exception handler enforcing the error contract. Nothing internal
leaks: raw exceptions, stack traces, and DB errors are logged with the trace id
and replaced by a plain-language message + machine-readable code."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied as DjPermissionDenied
from django.db import DatabaseError, IntegrityError
from django.http import Http404
from loguru import logger
from rest_framework import exceptions as drf_exc
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler

from docai.exceptions import DocAIError
from docai.logging.context import get_trace_id
from docai.logging.sanitize import exception_context

_DRF_CODES = {
    drf_exc.ValidationError: ("VALIDATION_ERROR", "Validation failed."),
    drf_exc.ParseError: ("PARSE_ERROR", "The request body could not be parsed."),
    drf_exc.AuthenticationFailed: ("AUTHENTICATION_FAILED", "Authentication failed."),
    drf_exc.NotAuthenticated: ("NOT_AUTHENTICATED", "Authentication is required."),
    drf_exc.PermissionDenied: (
        "PERMISSION_DENIED",
        "You do not have permission to perform this action.",
    ),
    drf_exc.NotFound: ("NOT_FOUND", "The requested resource was not found."),
    drf_exc.MethodNotAllowed: ("METHOD_NOT_ALLOWED", "This method is not allowed."),
    drf_exc.NotAcceptable: ("NOT_ACCEPTABLE", "The requested format is not available."),
    drf_exc.UnsupportedMediaType: ("UNSUPPORTED_MEDIA_TYPE", "Unsupported media type."),
    drf_exc.Throttled: ("RATE_LIMITED", "Too many requests. Please slow down."),
}


def _envelope(message, code, status_code, errors=None, headers=None):
    return Response(
        {
            "success": False,
            "message": message,
            "errors": error_details(errors, default_code=code.lower()),
            "error_code": code,
            "trace_id": get_trace_id(),
        },
        status=status_code,
        headers=headers,
    )


def docai_exception_handler(exc, context):
    trace = get_trace_id()
    request = context.get("request")
    if request is not None:
        # DRF handles these exceptions before Django's process_exception middleware runs.
        raw_request = getattr(request, "_request", request)
        raw_request._docai_exception_type = type(exc).__name__

    if isinstance(exc, DocAIError):
        logger.bind(
            trace_id=trace, event="api_error", error_code=exc.error_code, **exception_context(exc)
        ).log("ERROR" if exc.status_code >= 500 else "WARNING", exc.message)
        return _envelope(exc.message, exc.error_code, exc.status_code, exc.errors)

    if isinstance(exc, Http404):
        return _envelope("The requested resource was not found.", "NOT_FOUND", 404)
    if isinstance(exc, DjPermissionDenied):
        return _envelope(
            "You do not have permission to perform this action.", "PERMISSION_DENIED", 403
        )

    if isinstance(exc, drf_exc.APIException):
        # validation errors: 400 for malformed input, 422 when the body parsed
        # but failed business validation (DRF ValidationError) — the spec asks
        # for the most specific code.
        for klass, (code, msg) in _DRF_CODES.items():
            if isinstance(exc, klass):
                resp = drf_handler(exc, context)
                if resp is None:
                    return _envelope(msg, code, exc.status_code)
                errors = resp.data if isinstance(resp.data, (dict, list)) else {"detail": resp.data}
                http = exc.status_code
                if isinstance(exc, drf_exc.ValidationError):
                    http = status.HTTP_422_UNPROCESSABLE_ENTITY
                headers = {
                    key: value
                    for key, value in resp.headers.items()
                    if key.lower() not in {"content-length", "content-type"}
                }
                return _envelope(msg, code, http, errors, headers)
        resp = drf_handler(exc, context)
        return _envelope("Request failed.", "REQUEST_FAILED", resp.status_code if resp else 400)

    if isinstance(exc, IntegrityError):
        logger.bind(trace_id=trace, **exception_context(exc)).warning("integrity error")
        return _envelope("The request conflicts with existing data.", "CONFLICT", 409)
    if isinstance(exc, DatabaseError):
        logger.bind(trace_id=trace, **exception_context(exc)).error("database error")
        return _envelope("A storage error occurred. Please try again.", "DATABASE_ERROR", 503)

    logger.bind(trace_id=trace, **exception_context(exc)).error("unhandled error")
    return _envelope(
        "An unexpected error occurred. Reference this trace id when reporting it.",
        "INTERNAL_ERROR",
        500,
    )


def error_details(
    errors, *, default_code: str = "invalid", field: str = ""
) -> list[dict[str, str]]:
    """Flatten every error source to one stable, code-preserving shape."""
    if errors in (None, {}, []):
        return []
    if isinstance(errors, dict):
        details: list[dict[str, str]] = []
        for key, value in errors.items():
            nested_field = f"{field}.{key}" if field else str(key)
            details.extend(error_details(value, default_code=default_code, field=nested_field))
        return details
    if isinstance(errors, (list, tuple)):
        details = []
        for value in errors:
            details.extend(error_details(value, default_code=default_code, field=field))
        return details
    return [
        {
            "field": field,
            "message": str(errors),
            "code": str(getattr(errors, "code", default_code)),
        }
    ]
