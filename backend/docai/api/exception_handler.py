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


def _envelope(message, code, status_code, errors=None):
    return Response(
        {
            "success": False,
            "message": message,
            "errors": errors or {},
            "error_code": code,
            "trace_id": get_trace_id(),
        },
        status=status_code,
    )


def docai_exception_handler(exc, context):
    trace = get_trace_id()

    if isinstance(exc, DocAIError):
        logger.bind(trace_id=trace, error_code=exc.error_code).warning(
            "domain error: {} ({})", exc.error_code, type(exc).__name__
        )
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
                errors = resp.data if isinstance(resp.data, (dict, list)) else {"detail": resp.data}
                http = exc.status_code
                if isinstance(exc, drf_exc.ValidationError):
                    http = status.HTTP_422_UNPROCESSABLE_ENTITY
                    errors = _flatten_validation(errors)
                return _envelope(msg, code, http, errors)
        resp = drf_handler(exc, context)
        return _envelope("Request failed.", "REQUEST_FAILED", resp.status_code if resp else 400)

    if isinstance(exc, IntegrityError):
        logger.bind(trace_id=trace).warning("integrity error: {}", type(exc).__name__)
        return _envelope("The request conflicts with existing data.", "CONFLICT", 409)
    if isinstance(exc, DatabaseError):
        logger.bind(trace_id=trace).exception("database error")
        return _envelope("A storage error occurred. Please try again.", "DATABASE_ERROR", 503)

    logger.bind(trace_id=trace).exception("unhandled error")
    return _envelope(
        "An unexpected error occurred. Reference this trace id when reporting it.",
        "INTERNAL_ERROR",
        500,
    )


def _flatten_validation(errors):
    """Keep DRF's field→messages shape but coerce ErrorDetail objects to str."""
    if isinstance(errors, dict):
        return {k: _flatten_validation(v) for k, v in errors.items()}
    if isinstance(errors, list):
        return [_flatten_validation(v) for v in errors]
    return str(errors)
