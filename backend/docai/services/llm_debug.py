"""Opt-in local evidence diagnostics; never exposed through media or API endpoints."""

from __future__ import annotations

import json
import os
from uuid import uuid4

from django.conf import settings
from loguru import logger


def evidence_debug_capture(item):
    if item is None or not settings.DEBUG or not settings.DOCAI.get("LLM_DEBUG_CAPTURE", False):
        return None
    run_id, item_id, attempt = str(item.run_id), str(item.pk), item.attempts

    def capture(payload: dict) -> None:
        directory = settings.DOCAI_DATA_DIR / "debug" / "llm" / run_id / item_id
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        capture_id = uuid4().hex
        path = directory / f"{capture_id}.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {"run_id": run_id, "run_item_id": item_id, "attempt": attempt, **payload},
                stream,
                ensure_ascii=False,
                indent=2,
            )
        logger.bind(event="llm_debug_captured", capture_id=capture_id).info(
            "Local evidence diagnostic saved"
        )

    return capture
