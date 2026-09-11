from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from docai.admin_panels import processing_errors, worker_dashboard

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

urlpatterns = [
    # Custom admin URLs must precede the admin site's catch-all route.
    *admin_panel_urls,
    path("admin/", admin.site.urls),
    path("health/", include("health_check.urls")),  # readiness/liveness probes
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger"),
    path("api/", include("docai.api.urls")),  # /api/v1/...
]
