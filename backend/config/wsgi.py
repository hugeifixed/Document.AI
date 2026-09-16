import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
application = get_wsgi_application()

from docai.logging.startup import log_startup  # noqa: E402 -- Django settings/apps must be loaded

log_startup("web")
