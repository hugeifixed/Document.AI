"""Task runner abstraction. Business logic (services.runs.process_item) never
imports Celery. Local/Windows: sync or thread pool. Deployed: Celery. Another
scheduler = another runner class + a settings value."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import close_old_connections
from loguru import logger

from config.celery_runtime import broker_scheme


class SyncRunner:
    key = "sync"
    is_async = False

    def map(self, fn: Callable, ids: Iterable, **meta):
        for i in ids:
            fn(i)
        return False


class ThreadRunner:
    key = "thread"
    is_async = False

    def map(self, fn: Callable, ids: Iterable, **meta):
        ids = list(ids)
        workers = max(1, min(settings.DOCAI["MAX_WORKERS"], len(ids) or 1))
        if "sqlite" in settings.DATABASES["default"]["ENGINE"]:
            workers = 1   # SQLite is single-writer; parallelism needs PostgreSQL/Oracle

        def wrapped(i):
            try:
                return fn(i)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="docai") as ex:
            list(ex.map(wrapped, ids))
        return False


class CeleryRunner:
    key = "celery"
    is_async = True

    def map(self, fn: Callable, ids: Iterable, **meta):
        try:
            from celery import chord
        except ImportError as exc:
            raise ImproperlyConfigured(
                'DOCAI_TASK_RUNNER=celery requires `uv pip install -e ".[celery]"`.'
            ) from exc
        from docai.tasks.celery_tasks import finalize_run_task, process_run_item

        sig = [process_run_item.s(str(i)) for i in ids]
        if not sig:
            return False
        chord(sig)(finalize_run_task.s(meta.get("run_id")))
        logger.bind(
            run_id=meta.get("run_id"),
            items=len(sig),
            broker=broker_scheme(settings.CELERY_BROKER_URL),
            pool=settings.CELERY_WORKER_POOL,
        ).info("enqueued to celery")
        return True


def get_runner():
    key = settings.DOCAI["TASK_RUNNER"]
    runners = {"sync": SyncRunner, "thread": ThreadRunner, "celery": CeleryRunner}
    try:
        runner_class = runners[key]
    except KeyError as exc:
        raise ImproperlyConfigured(
            f"Unknown DOCAI_TASK_RUNNER={key!r}; use sync, thread, or celery."
        ) from exc
    return runner_class()
