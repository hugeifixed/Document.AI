"""Local extraction smoke tests using the normal workflow and preparation boundaries."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from django.conf import settings
from django.test.utils import override_settings
from pypdf import PdfReader

from docai.adapters.layout.base import get_layout_provider_for_format
from docai.exceptions import CorruptFile, EmptyFile, ProtectedFile, WorkflowConfigError
from docai.input_quality import prepare_input
from docai.models import Run, WorkflowConfiguration
from docai.workflows.base import WorkflowContext, get_strategy

from . import layouts, runs, workflow_snapshots
from .extraction_visualization import collect_labels, render_labels, write_labels

EXTRACTION_TYPES = frozenset({"extract_structured", "extract_unstructured", "extract_template"})


def workflow_context(
    workflow: WorkflowConfiguration, *, live: bool, citation_repair: bool | None = None
) -> WorkflowContext:
    """Read versions without creating a Run, seeding defaults, or editing the workflow."""
    if workflow.workflow_type not in EXTRACTION_TYPES:
        raise WorkflowConfigError("Choose an extraction-only workflow for this command.")
    snapshot = workflow_snapshots.capture(workflow)
    if citation_repair is not None:
        snapshot["config"]["citation_repair"] = citation_repair
    if not live:
        snapshot["adapters"] = {"layout": "pypdf", "llm": "mock"}
    options = (
        settings.DOCAI
        if live
        else {
            **settings.DOCAI,
            "LAYOUT_ADAPTER": "pypdf",
            "LLM_ADAPTER": "mock",
        }
    )
    with override_settings(DOCAI=options):
        return runs.build_context(Run(config_snapshot=snapshot))


def preview_file(source: Path, output: Path, context: WorkflowContext) -> dict:
    """Process exactly one PDF, leaving only local output artifacts."""
    started = time.monotonic()
    with source.open("rb") as stream:
        if not stream.read(1024).lstrip().startswith(b"%PDF-"):
            raise CorruptFile()
        stream.seek(0)
        sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    reader = PdfReader(source)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ProtectedFile()
    expected_pages = len(reader.pages)
    ctx = replace(context)  # Fresh stage observation and correction budget for each document.
    cfg = ctx.config
    layouts.validate_processing_policy(cfg.input_quality, cfg.di_analysis, ctx.layout_adapter_key)
    provider = get_layout_provider_for_format("pdf", ctx.layout_adapter_key)
    with prepare_input(source, source_format="pdf", config=cfg.input_quality) as prepared:
        layout_started = time.monotonic()
        layout = provider.analyze(
            prepared.path,
            document_id=str(uuid5(NAMESPACE_URL, "extraction-test:" + sha256)),
            source_format=prepared.source_format,
            pages=prepared.selected_pages,
            ocr_high_resolution=cfg.di_analysis.ocr_high_resolution,
        )
        # Use the same original-page completion and integrity check as normal processing.
        layouts._complete_pages(layout, prepared.page_details, expected_page_count=expected_pages)
        if not any(unit.content.strip() for unit in layout.units):
            raise EmptyFile("No readable text; use --live with an OCR adapter for scanned PDFs.")
        layout_ms = round((time.monotonic() - layout_started) * 1000)
        extraction_started = time.monotonic()
        result = get_strategy(ctx.workflow_type).process_document(ctx, layout)
        extraction_ms = round((time.monotonic() - extraction_started) * 1000)
        labels = collect_labels(result, layout)
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_labels(output, labels)
        (output / "layout.json").write_text(layout.model_dump_json(indent=2), encoding="utf-8")
        summary = {
            "status": "extracted",
            "source_sha256": sha256,
            "pages": expected_pages,
            "labels": len(labels),
            "boxed": sum(label["boxed"] for label in labels),
            "unboxed": sum(not label["boxed"] for label in labels),
            "images": [],
            "layout_adapter": provider.key,
            "llm_adapter": ctx.llm.key,
            "layout_ms": layout_ms,
            "extraction_ms": extraction_ms,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "rejected_chunks": result.rejected_extraction_chunks,
        }
        payload = {
            "summary": summary,
            "config": cfg.model_dump(mode="json", by_alias=True),
            "prompts": {
                stage: {"name": p.name, "version": p.version} for stage, p in ctx.prompts.items()
            },
            "input_quality": prepared.summary,
            "template": vars(ctx).get("template"),
            "result": asdict(result),
        }
        # Preserve costly extraction output even if optional image rendering fails.
        (output / "result.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        summary.update(
            images=render_labels(prepared.path, output, labels, layout=layout, title=source.name),
            status="succeeded",
        )
        summary["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        (output / "result.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return summary
