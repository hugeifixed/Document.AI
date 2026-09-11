"""JSON responses for failures raised outside DRF's normal exception path."""

from __future__ import annotations

from django.conf import settings
from django.http import JsonResponse
from django.views.csrf import csrf_failure as django_csrf_failure
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from docai.api.exception_handler import error_details
from docai.logging.context import get_trace_id


def csrf_failure(request, reason=""):
    """Keep API CSRF failures on the public JSON error contract."""
    if not request.path.startswith("/api/"):
        return django_csrf_failure(request, reason=reason)
    return JsonResponse(
        {
            "success": False,
            "message": "CSRF verification failed. Refresh the session and try again.",
            "errors": error_details(
                "A valid CSRF token is required for this request.",
                default_code="csrf_failed",
                field="csrf",
            ),
            "error_code": "CSRF_FAILED",
            "trace_id": get_trace_id(),
        },
        status=403,
    )


class APINotFoundView(APIView):
    """Turn unmatched /api/ routes into the same JSON 404 as matched routes."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    schema = None

    def not_found(self, request, *args, **kwargs):
        detail = "No API route matches this URL."
        if settings.DEBUG:
            detail += " Open /api/ to browse the interactive API documentation."
            if settings.SILKY_ENABLED and request.path.rstrip("/") in {
                "/api/silk",
                "/api/profiler",
            }:
                detail += " The request profiler is an admin tool at /admin/profiler/."
        raise NotFound(detail=detail)

    get = post = put = patch = delete = head = options = not_found
