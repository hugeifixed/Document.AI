"""Startup configuration summaries without network probes or secret values."""

from __future__ import annotations

import os
import platform

import django
from django.conf import settings
from loguru import logger

from config.celery_runtime import current_task_runtime_policy


def log_startup(role: str) -> None:
    """Called by WSGI initialization / Celery ready, never by AppConfig.ready.

    This avoids logging a server startup for migrations, tests, and the development
    autoreloader's supervisor. WSGI initialization does not imply socket readiness.
    """
    policy = current_task_runtime_policy()
    logger.bind(
        event="runtime_startup",
        role=role,
        pid=os.getpid(),
        python=platform.python_version(),
        django=django.get_version(),
        os=platform.system(),
        app_version=settings.DOCAI["PLATFORM_VERSION"],
        build=settings.DOCAI_BUILD_SHA,
        debug=settings.DEBUG,
        settings_module=settings.SETTINGS_MODULE,
    ).info("DocAI runtime initialized")
    logger.bind(
        event="runtime_configuration",
        database=policy.database_engine.rsplit(".", 1)[-1],
        cache=str(settings.CACHES["default"]["BACKEND"]).rsplit(".", 1)[-1],
        storage=str(settings.STORAGES["default"]["BACKEND"]).rsplit(".", 1)[-1],
        task_runner=policy.runner,
        configured_slots=1
        if policy.runner == "celery" and policy.worker_pool == "solo"
        else policy.executor_capacity,
        configured_pool=policy.worker_pool if policy.runner == "celery" else "",
        broker=policy.broker if policy.runner == "celery" else "",
        sqlite_inline=policy.runner == "thread" and policy.uses_sqlite,
        layout_adapter=settings.DOCAI["LAYOUT_ADAPTER"],
        llm_adapter=settings.DOCAI["LLM_ADAPTER"],
    ).info("Runtime configuration")
    logger.bind(
        event="azure_network_configuration",
        proxy_env_configured=any(
            os.environ.get(name)
            for name in (
                "HTTPS_PROXY",
                "https_proxy",
                "HTTP_PROXY",
                "http_proxy",
                "ALL_PROXY",
                "all_proxy",
            )
        ),
        proxy_bypass_configured=bool(os.environ.get("no_proxy") or os.environ.get("NO_PROXY")),
        verify_ssl=settings.AZURE_VERIFY_SSL,
        identity_di_ca="custom" if os.environ.get("REQUESTS_CA_BUNDLE") else "default",
        llm_ca="custom"
        if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR")
        else "default",
        timeout_s=settings.DOCAI["AZURE_TIMEOUT_S"],
    ).info("Azure network configuration")
    if not settings.AZURE_VERIFY_SSL:
        logger.warning("Azure TLS verification is disabled for local debugging")
