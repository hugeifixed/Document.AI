"""Authentication behavior shared by local and production API settings."""

from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import SessionAuthentication


class ChallengeSessionAuthentication(SessionAuthentication):
    """Return HTTP 401 for a missing session while keeping CSRF failures at 403."""

    def authenticate_header(self, request):
        return 'Session realm="api"'


class ChallengeSessionAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "docai.api.authentication.ChallengeSessionAuthentication"
    name = "cookieAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": settings.SESSION_COOKIE_NAME,
            "description": "Django session cookie established by the login endpoint.",
        }
