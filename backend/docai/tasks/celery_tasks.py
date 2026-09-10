"""Thin Celery shims. Only imported when TASK_RUNNER=celery. Idempotent and
retry-safe because the underlying service is; dead-letter via settings."""
from __future__ import annotations

try:
    from celery import shared_task
except ImportError:  # celery is an optional extra
    def shared_task(*a, **k):  # type: ignore
        def deco(f):
            return f
        return deco


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3},
             acks_late=True, queue="docai")
def process_run_item(self, item_id: str):
    from docai.services.runs import process_item
    return process_item(item_id)


@shared_task(queue="docai")
def finalize_run_task(results, run_id: str):
    from docai.services.runs import finalize_run
    return str(finalize_run(run_id).status)


@shared_task(queue="docai.ingest")
def build_layout_task(document_id: str):
    from docai.models import Document
    from docai.services.layouts import get_or_build_layout
    get_or_build_layout(Document.objects.get(id=document_id))
    return document_id
