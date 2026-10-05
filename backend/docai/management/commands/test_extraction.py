"""Run a saved extraction workflow against local documents and write visual evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from docai.exceptions import WorkflowConfigError
from docai.models import WorkflowConfiguration
from docai.services.extraction_preview import INPUT_EXTENSIONS, preview_file, workflow_context
from docai.services.extraction_visualization import RendererUnavailable, check_renderer


class Command(BaseCommand):
    help = (
        "Test a saved extraction workflow on PDF/JPG/PNG/TIFF files; export JPGs, labels and JSON."
    )

    def add_arguments(self, parser):
        parser.add_argument("--workflow-id", type=UUID, required=True)
        parser.add_argument(
            "--input", type=Path, required=True, help="PDF/JPG/JPEG/PNG/TIF/TIFF file or folder."
        )
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument(
            "--live",
            action="store_true",
            help="Use configured adapters; default uses pypdf + mock.",
        )
        parser.add_argument("--recursive", action="store_true", help="Include input subfolders.")
        parser.add_argument(
            "--citation-repair",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Override citation repair for this test; default follows the workflow (off unless enabled).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=10,
            help="Maximum files, in sorted path order (default 10).",
        )

    def handle(self, *args, **opts):
        source, output = (
            Path(opts["input"]).expanduser().resolve(),
            Path(opts["output"]).expanduser().resolve(),
        )
        if opts["limit"] < 1:
            raise CommandError("--limit must be positive.")
        if not source.exists():
            raise CommandError("Input does not exist.")
        if source.is_dir():
            if source == output:
                raise CommandError("Choose an output directory different from the input directory.")
            paths = sorted(
                path
                for path in (source.rglob("*") if opts["recursive"] else source.iterdir())
                if path.is_file()
                and path.suffix.lower() in INPUT_EXTENSIONS
                and not (output.is_relative_to(source) and path.resolve().is_relative_to(output))
            )
        elif source.is_file() and source.suffix.lower() in INPUT_EXTENSIONS:
            paths = [source]
        else:
            raise CommandError("Input must be a PDF/JPG/JPEG/PNG/TIF/TIFF file or a folder.")
        if not paths:
            raise CommandError("No PDF/JPG/JPEG/PNG/TIF/TIFF files found.")
        workflow = WorkflowConfiguration.objects.filter(
            pk=opts["workflow_id"],
            project__is_removed=False,
        ).first()
        if workflow is None:
            raise CommandError("Workflow ID was not found.")
        try:
            check_renderer()
            ctx = workflow_context(
                workflow, live=opts["live"], citation_repair=opts["citation_repair"]
            )
        except Exception as exc:  # noqa: BLE001 -- local command boundary, never print provider content
            raise CommandError(
                str(exc)
                if isinstance(exc, (RendererUnavailable, WorkflowConfigError))
                else f"Test setup failed ({getattr(exc, 'error_code', type(exc).__name__)})."
            ) from None
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        manifest = {
            "workflow": {
                "id": str(workflow.id),
                "name": workflow.name,
                "version": workflow.version,
                "type": workflow.workflow_type,
                "hash": workflow.content_hash,
            },
            "mode": "configured" if opts["live"] else "offline",
            "citation_repair": ctx.config.citation_repair,
            "selected": min(len(paths), opts["limit"]),
            "omitted": max(0, len(paths) - opts["limit"]),
            "documents": [],
        }
        failed = 0
        for path in paths[: opts["limit"]]:
            relative = path.relative_to(source) if source.is_dir() else Path(path.name)
            # Retain subdirectories and the full filename to avoid name/case collisions.
            destination = output / relative.parent / (relative.name + ".extraction")
            try:
                summary = preview_file(path, destination, ctx)
                self.stdout.write(
                    f"{relative}: {summary['labels']} labels, {summary['boxed']} boxed, {summary['unboxed']} unboxed"
                )
            except Exception as exc:  # noqa: BLE001 -- one failed file must not discard the other results
                failed += 1
                summary = {
                    "status": "failed",
                    "error_code": getattr(exc, "error_code", "EXTRACTION_TEST_FAILED"),
                    "error_type": type(exc).__name__,
                }
                destination.mkdir(parents=True, exist_ok=True, mode=0o700)
                (destination / "error.json").write_text(
                    json.dumps(summary, indent=2), encoding="utf-8"
                )
                self.stderr.write(f"{relative}: failed ({summary['error_code']})")
            manifest["documents"].append(
                {"input": str(relative), "output": str(destination.relative_to(output)), **summary}
            )
            (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self.stdout.write(
            f"Outputs: {output} ({len(manifest['documents']) - failed} succeeded, {failed} failed; {manifest['omitted']} omitted)"
        )
        if failed:
            raise CommandError(f"{failed} file(s) failed; details are in manifest.json.")
