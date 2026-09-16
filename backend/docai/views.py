"""Small server-rendered views that must remain available without the React app."""

from __future__ import annotations

import datetime
from typing import Any, cast

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.utils.feedgenerator import Atom1Feed, Rss201rev2Feed
from django.views.decorators.cache import never_cache
from health_check.views import HealthCheckView

from config.celery_runtime import current_task_runtime_policy
from docai.health import DependencyCheck, extended_checks

CORE_HEALTH_CHECKS = (
    "health_check.Cache",
    "health_check.Database",
    "health_check.Storage",
)

_CHECK_NAMES = {
    "Cache": ("cache", "Cache"),
    "Database": ("database", "Database"),
    "Storage": ("storage", "Document storage"),
}
_CHECK_DESCRIPTIONS = {
    "cache": "Application cache read and write",
    "database": "Primary application database",
    "storage": "Document storage read, write, and delete",
}


def _service_name(result: Any) -> tuple[str, str]:
    if isinstance(result.check, DependencyCheck):
        return result.check.key, result.check.label
    class_name = result.check.__class__.__name__
    return _CHECK_NAMES.get(class_name, (class_name.lower(), class_name))


@never_cache
def health_liveness(request: HttpRequest) -> JsonResponse:
    """Confirm only that Django can serve a request; do not touch dependencies."""
    del request
    return JsonResponse({"status": "ok"})


class SystemHealthView(HealthCheckView):
    """Public, sanitized dependency status for people and monitoring clients."""

    template_name = "docai/health/status.html"
    checks = CORE_HEALTH_CHECKS
    include_extended = True

    def get_checks(self):
        yield from super().get_checks()
        if self.include_extended:
            yield from extended_checks()

    async def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        response = cast(HttpResponse, await super().get(request, *args, **kwargs))
        if response.status_code == 500:
            response.status_code = 503
        return response

    def _summary(self) -> dict[str, Any]:
        checked_at = timezone.now()
        checks = []
        for result in self.results:
            key, label = _service_name(result)
            diagnostic = isinstance(result.check, DependencyCheck)
            checks.append(
                {
                    "key": key,
                    "label": label,
                    "status": "unavailable" if result.error else "ok",
                    "latency_ms": round(result.time_taken * 1000, 1),
                    "slow": result.time_taken >= 1.0,
                    "diagnostic": diagnostic,
                    "description": result.check.description
                    if diagnostic
                    else _CHECK_DESCRIPTIONS.get(key, ""),
                    "detail": result.check.detail if diagnostic else "",
                }
            )
        healthy = all(check["status"] == "ok" for check in checks)
        return {
            "status": "ok" if healthy else "unavailable",
            "checked_at": checked_at,
            "checks": checks,
            "core_checks": [check for check in checks if not check["diagnostic"]],
            "diagnostics": [check for check in checks if check["diagnostic"]],
        }

    def _processing_context(self) -> dict[str, str]:
        policy = current_task_runtime_policy()
        if policy.runner == "celery":
            capacity = 1 if policy.worker_pool == "solo" else policy.executor_capacity
            return {
                "label": "Celery",
                "detail": f"{policy.worker_pool} pool · {capacity} configured slot{'s' if capacity != 1 else ''}",
            }
        if policy.runner == "thread":
            return {
                "label": "Thread runner",
                "detail": f"Runs in the web process · {policy.executor_capacity} configured worker{'s' if policy.executor_capacity != 1 else ''}",
            }
        return {"label": "Synchronous", "detail": "Runs in the web request process"}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        summary = self._summary()
        return {
            **super().get_context_data(**kwargs),
            **summary,
            "all_healthy": summary["status"] == "ok",
            "environment": settings.DOCAI_ENVIRONMENT.upper(),
            "platform_version": settings.DOCAI["PLATFORM_VERSION"],
            "build_sha": settings.DOCAI_BUILD_SHA,
            "processing": self._processing_context(),
            "frontend_url": settings.DOCAI_FRONTEND_URL,
        }

    def render_to_response_json(self, status: int) -> JsonResponse:
        summary = self._summary()
        return JsonResponse(
            {
                "status": summary["status"],
                "checked_at": summary["checked_at"].isoformat(),
                "checks": {
                    check["key"]: {
                        "status": check["status"],
                        "latency_ms": check["latency_ms"],
                        **({"detail": check["detail"]} if check["detail"] else {}),
                    }
                    for check in summary["checks"]
                },
            },
            status=status,
        )

    def render_to_response_text(self, status: int) -> HttpResponse:
        summary = self._summary()
        lines = [f"status: {summary['status']}"]
        lines.extend(f"{check['key']}: {check['status']}" for check in summary["checks"])
        return HttpResponse(
            "\n".join(lines) + "\n", content_type="text/plain; charset=utf-8", status=status
        )

    def _render_feed(self, feed_class: type[Atom1Feed] | type[Rss201rev2Feed]) -> HttpResponse:
        """Retain feed compatibility without exposing provider exception messages."""
        summary = self._summary()
        feed = feed_class(
            title="DocAI system health",
            link=self.request.build_absolute_uri(self.request.path),
            description="Current core dependency status",
            feed_url=self.request.build_absolute_uri(),
        )
        for check in summary["checks"]:
            checked_at: datetime.datetime = summary["checked_at"]
            feed.add_item(
                title=check["label"],
                link=self.request.build_absolute_uri(self.request.path),
                description=check["status"],
                pubdate=checked_at,
                updateddate=checked_at,
                author_name="DocAI",
                categories=[check["status"]],
            )
        response = HttpResponse(
            feed.writeString("utf-8"), content_type=feed.content_type, status=200
        )
        patch_vary_headers(response, ["Accept"])
        return response


class ReadinessHealthView(SystemHealthView):
    """Stable JSON readiness contract for load balancers and orchestrators."""

    include_extended = False

    async def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        query = request.GET.copy()
        query["format"] = "json"
        cast(Any, request).GET = query
        return await super().get(request, *args, **kwargs)
