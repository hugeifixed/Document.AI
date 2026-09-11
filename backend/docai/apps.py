from django.apps import AppConfig


class DocaiConfig(AppConfig):
    name = "docai"
    verbose_name = "Document AI Platform"

    def ready(self):
        from docai.logging.setup import configure_logging

        configure_logging()
        from docai import (
            checks,  # noqa: F401  (register deployment checks)
            signals,  # noqa: F401  (cache invalidation hooks)
        )
