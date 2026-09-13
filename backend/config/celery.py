"""Optional Celery application configured entirely through Django settings."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
try:
    from celery import Celery, signals
except ImportError:  # pragma: no cover
    app = None
else:
    app = Celery("docai")
    app.config_from_object("django.conf:settings", namespace="CELERY")
    app.autodiscover_tasks()

    @signals.setup_logging.connect
    def setup_worker_logging(loglevel=None, logfile=None, colorize=None, **kwargs):
        # Keep Celery, SDKs and domain milestones on the same redacted sinks.
        from docai.logging.setup import configure_logging

        configure_logging(worker=True, level=loglevel, logfile=logfile, colorize=colorize)
