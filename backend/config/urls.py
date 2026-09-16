from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView

from docai.admin_panels import processing_errors, worker_dashboard
from docai.api.documentation import (
    AgentGuideView,
    IntegrationGuideView,
    ScalarView,
    SwaggerView,
    llms_discovery,
)
from docai.views import ReadinessHealthView, SystemHealthView, health_liveness

admin_panel_urls = [
    path("admin/cache/", include("dj_cache_panel.urls")),
    path("admin/errors/", processing_errors, name="processing_errors"),
    path("admin/workers/", worker_dashboard, name="worker_dashboard"),
    path("admin/dj-control-room-base/", include("dj_control_room_base.urls")),
]
if "dj_celery_panel" in settings.INSTALLED_APPS:
    admin_panel_urls.append(path("admin/celery/", include("dj_celery_panel.urls")))
if "dj_redis_panel" in settings.INSTALLED_APPS:
    admin_panel_urls.append(path("admin/redis/", include("dj_redis_panel.urls")))
if settings.SILKY_ENABLED:
    admin_panel_urls.append(path("admin/profiler/", include("silk.urls", namespace="silk")))

urlpatterns = [
    # Custom admin URLs must precede the admin site's catch-all route.
    *admin_panel_urls,
    path("admin/", admin.site.urls),
    path("health/", SystemHealthView.as_view(), name="health_check"),
    path("health/live/", health_liveness, name="health_liveness"),
    path("health/ready/", ReadinessHealthView.as_view(), name="health_readiness"),
    path("api/", RedirectView.as_view(pattern_name="swagger", permanent=False), name="api-root"),
    path("api/schema/", SpectacularAPIView.as_view(api_version="v1"), name="schema"),
    path("api/docs/", SwaggerView.as_view(url_name="schema"), name="swagger"),
    path("api/docs/scalar/", ScalarView.as_view(), name="scalar"),
    path("api/docs/integration.md", IntegrationGuideView.as_view(), name="api-integration-guide"),
    path("api/llms.txt", AgentGuideView.as_view(), name="api-llms-txt"),
    path("llms.txt", llms_discovery, name="llms-txt"),
    path("api/", include("docai.api.urls")),  # /api/v1/...
]
