"""Documentation delivery shares Spectacular's access policy, not business API envelopes."""

from importlib.resources import files
from typing import cast

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import Http404, HttpResponse
from django.middleware.csrf import get_token
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_GET
from drf_spectacular import settings as schema_settings
from drf_spectacular.views import SpectacularSwaggerView
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.renderers import BaseRenderer, TemplateHTMLRenderer
from rest_framework.response import Response
from rest_framework.settings import api_settings, perform_import
from rest_framework.views import APIView

SCALAR_ASSET = "docai/vendor/scalar/1.68.0/standalone.js"


class TextRenderer(BaseRenderer):
    media_type = "text/plain"
    format = "txt"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return str(data).encode("utf-8")


class MarkdownRenderer(TextRenderer):
    media_type = "text/markdown"
    format = "md"


class DocumentationAccess(APIView):
    """Keep HTML and text access aligned when deployment authentication changes."""

    def get_permissions(self):
        classes = settings.SPECTACULAR_SETTINGS.get(
            "SERVE_PERMISSIONS", schema_settings.SPECTACULAR_DEFAULTS["SERVE_PERMISSIONS"]
        )
        resolved = cast(list[type[BasePermission]], perform_import(classes, "SERVE_PERMISSIONS"))
        return [permission() for permission in resolved]

    def get_authenticators(self):
        classes = settings.SPECTACULAR_SETTINGS.get("SERVE_AUTHENTICATION")
        if classes is None:
            resolved = cast(
                list[type[BaseAuthentication]], api_settings.DEFAULT_AUTHENTICATION_CLASSES
            )
        else:
            resolved = cast(
                list[type[BaseAuthentication]], perform_import(classes, "SERVE_AUTHENTICATION")
            )
        return [authentication() for authentication in resolved]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        # Never cache authenticated HTML containing a CSRF token in a shared proxy.
        response["Cache-Control"] = "private, no-store"
        patch_vary_headers(response, ("Cookie", "Authorization"))
        response["Link"] = f'<{reverse("api-llms-txt")}>; rel="describedby"'
        return response


class SwaggerView(DocumentationAccess, SpectacularSwaggerView):
    schema = None
    template_name = "docai/docs/swagger.html"

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        response.data["scalar_enabled"] = settings.DOCAI_SCALAR_ENABLED
        return response


class AgentGuideView(DocumentationAccess):
    schema = None
    renderer_classes = [TextRenderer]

    def get(self, request):
        return Response(
            render_to_string(
                "docai/docs/llms.txt",
                {"scalar_enabled": settings.DOCAI_SCALAR_ENABLED},
            )
        )


class IntegrationGuideView(DocumentationAccess):
    schema = None
    renderer_classes = [MarkdownRenderer]

    def get(self, request):
        # Package the canonical guide with Django; serving it must not require a repo checkout.
        guide = files("docai").joinpath("docs/integration.md").read_text(encoding="utf-8")
        return HttpResponse(guide, content_type="text/markdown; charset=utf-8")


class ScalarView(DocumentationAccess):
    schema = None
    renderer_classes = [TemplateHTMLRenderer]

    def get(self, request):
        if not settings.DOCAI_SCALAR_ENABLED:
            raise Http404
        ready = bool(finders.find(SCALAR_ASSET))
        response = Response(
            {
                "scalar_enabled": True,
                "scalar_ready": ready,
                "scalar_asset": SCALAR_ASSET,
                "scalar_config": {
                    "url": reverse("schema") + "?format=json",
                    "theme": "none",
                    "withDefaultFonts": False,
                    "telemetry": False,
                    "persistAuth": False,
                    "proxyUrl": "",
                    "agent": {"disabled": True},
                    "mcp": {"disabled": True},
                    "hideClientButton": True,
                    "showDeveloperTools": "never",
                },
                "csrf_config": {
                    "token": get_token(request),
                    "cookie": settings.CSRF_COOKIE_NAME,
                    "header": settings.CSRF_HEADER_NAME.removeprefix("HTTP_").replace("_", "-"),
                },
            },
            template_name="docai/docs/scalar.html",
            status=200 if ready else 503,
        )
        response["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        return response


@require_GET
def llms_discovery(request):
    """Public navigation only; the linked guide retains the deployed docs permissions."""
    return HttpResponse(
        "# DocAI\n\n> Document processing API documentation.\n\n"
        "Documentation may require authentication.\n\n## Documentation\n\n"
        f"- [Agent integration guide]({reverse('api-llms-txt')}): Start here.\n",
        content_type="text/plain; charset=utf-8",
    )
