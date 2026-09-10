"""Optional Celery application configured entirely through Django settings."""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
try:
    from celery import Celery
except ImportError:  # pragma: no cover
    app = None
else:
    app = Celery("docai")
    app.config_from_object("django.conf:settings", namespace="CELERY")
    app.autodiscover_tasks()
