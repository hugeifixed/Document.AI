from . import base as base_settings
from .base import *  # noqa: F403

DOCAI_ENVIRONMENT = "local"
DEBUG = True
AZURE_DI_API_KEY = base_settings.env.str("AZURE_DI_API_KEY", "").strip()
AZURE_OPENAI_API_KEY = base_settings.env.str("AZURE_OPENAI_API_KEY", "").strip()
ALLOWED_HOSTS = base_settings.env.list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "[::1]"])

# The Vite development server uses a separate origin. Deployments default to
# the same-origin root in base settings and can override this URL when needed.
DOCAI_FRONTEND_URL = (
    base_settings.env.str("DOCAI_FRONTEND_URL", "http://localhost:5173/").strip()
    or "http://localhost:5173/"
)
UNFOLD = {**base_settings.UNFOLD, "SITE_URL": DOCAI_FRONTEND_URL}
