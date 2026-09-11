from . import base as base_settings
from .base import *  # noqa: F403

DOCAI_ENVIRONMENT = "local"
DEBUG = True
ALLOWED_HOSTS = base_settings.env.list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "[::1]"])
