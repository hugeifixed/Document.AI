from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    # Custom admin URLs must precede the admin site's catch-all route.
    path("admin/cache/", include("dj_cache_panel.urls")),
    path("admin/dj-control-room-base/", include("dj_control_room_base.urls")),
    path("admin/", admin.site.urls),
    path("health/", include("health_check.urls")),          # readiness/liveness probes
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger"),
    path("api/", include("docai.api.urls")),                # /api/v1/...
]
