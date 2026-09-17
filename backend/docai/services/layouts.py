"""Immutable layouts and exact input representations, scoped by document and policy.

Scalar hashes support SQLite and Oracle without comparing JSON/NCLOB metadata.
A completed artifact and its units are published together; subsequent runs never
replace units referenced by historical results or ground-truth geometry.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from loguru import logger

from docai.adapters.layout.base import get_layout_provider_for_format
from docai.adapters.storage import (
    artifact_path,
    local_path,
    open_file,
    read_bytes,
    save_bytes,
    save_file,
)
from docai.exceptions import (
    EmptyFile,
    IntegrationError,
    NotFound,
    UnsupportedFile,
    WorkflowConfigError,
)
from docai.models import ARTIFACT_KIND, Document, ProcessingArtifact, RunItem, SourceUnit
from docai.schemas.config import DIAnalysisConfig, InputQualityConfig
from docai.schemas.layout import LayoutDocument, LayoutPage

from .checkpoints import active_claim

if TYPE_CHECKING:
    from docai.input_quality import PreparedInput


@contextmanager
def _source_file(doc: Document) -> Iterator[Path]:
    """Yield a local source path and remove any remote-storage staging file."""
    path = local_path(doc.storage_path)
    if path:
        yield Path(path)
        return
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{doc.file_format}", delete=False) as target:
            temporary_path = Path(target.name)
            with open_file(doc.storage_path) as source:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        if temporary_path is None:  # pragma: no cover
            raise RuntimeError("Temporary source file was not created.")
        yield temporary_path
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def artifact_for_document(doc: Document, run_id: Any = None) -> ProcessingArtifact | None:
    """A supplied run must contain this document; missing layout never means latest."""
    if run_id is not None:
        try:
            run_id = UUID(str(run_id))
        except (TypeError, ValueError):
            raise NotFound("That run does not contain this document.") from None
        item = (
            RunItem.objects.filter(document=doc, run_id=run_id)
            .select_related("layout_artifact", "layout_artifact__source_artifact")
            .first()
        )
        if item is None:
            raise NotFound("That run does not contain this document.")
        return item.layout_artifact
    return (
        doc.artifacts.filter(kind=ARTIFACT_KIND.layout)
        .select_related("source_artifact")
        .order_by("-created", "-id")
        .first()
    )


def units_for_artifact(doc: Document, artifact: ProcessingArtifact | None):
    return doc.units.filter(layout_artifact=artifact).order_by("index")


def read_artifact_layout(artifact: ProcessingArtifact | None) -> LayoutDocument | None:
    if artifact is None:
        return None
    return LayoutDocument.model_validate_json(read_bytes(artifact.storage_path).decode("utf-8"))


def load_layout(doc: Document, *, run_id: Any = None) -> LayoutDocument | None:
    return read_artifact_layout(artifact_for_document(doc, run_id))


def _distribution_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unavailable"


def _policy_key(
    doc: Document, adapter: str, quality: InputQualityConfig, analysis: DIAnalysisConfig
) -> str:
    from docai.input_quality import PROCESSOR_REVISION

    packages = {"pypdf": "pypdf", "excel": "openpyxl", "azure_di": "azure-ai-documentintelligence"}
    adapter_version = _distribution_version(packages[adapter]) if adapter in packages else "1"
    policy = {
        "representation": 1,
        "document": str(doc.pk),
        "source": doc.sha256,
        "format": doc.file_format,
        "adapter": adapter,
        "adapter_version": adapter_version,
        "input_quality": quality.model_dump(),
        **({"processor_revision": PROCESSOR_REVISION} if quality.mode == "adaptive" else {}),
        "processor_versions": {
            package: _distribution_version(package)
            for package in ("Pillow", "opencv-python-headless", "pypdfium2")
        }
        if quality.mode == "adaptive"
        else {},
        "processor_limits": {
            name: getattr(settings, name)
            for name in (
                "DOCAI_IMAGE_NORMALIZATION_MAX_PIXELS",
                "DOCAI_IMAGE_NORMALIZATION_MAX_DIMENSION",
                "DOCAI_IMAGE_NORMALIZATION_MAX_OUTPUT_MB",
            )
        }
        if quality.mode == "adaptive"
        else {},
        "di_analysis": analysis.model_dump(),
        "api_version": settings.DOCAI.get("AZURE_DI_API_VERSION", "")
        if adapter == "azure_di"
        else "",
        "endpoint": settings.DOCAI.get("AZURE_DI_ENDPOINT", "") if adapter == "azure_di" else "",
        "model_id": "prebuilt-layout" if adapter == "azure_di" else "",
        "features": ["keyValuePairs"] if adapter == "azure_di" else [],
    }
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def _complete_pages(
    layout: LayoutDocument, details: list[dict], *, expected_page_count: int | None = None
) -> None:
    """Retain original numbers and distinguish native text from DI OCR output."""
    original_pages = layout.pages
    pages = {page.number: page for page in original_pages}
    invalid_numbering = len(pages) != len(original_pages) or any(
        page.index != page.number - 1 for page in original_pages
    )
    for detail in details:
        number = int(detail["page"])
        page = pages.get(number)
        if detail["status"] == "skipped":
            page = LayoutPage(
                number=number,
                index=number - 1,
                width=detail.get("width"),
                height=detail.get("height"),
                unit=detail.get("unit"),
                has_text_layer=bool(detail.get("has_text_layer", False)),
                excluded_from_analysis=True,
            )
            pages[number] = page
        if page is not None:
            page.has_text_layer = bool(detail.get("has_text_layer", False))
    expected = (
        set(range(1, expected_page_count + 1))
        if expected_page_count is not None
        else {int(detail["page"]) for detail in details}
    )
    if invalid_numbering or (expected and expected != set(pages)):
        coverage = len(expected.intersection(pages))
        reason = (
            f"Layout analysis covered {coverage} of {len(expected)} expected pages. "
            "Processing stopped to avoid incomplete results. Check the service page limit "
            "or pricing tier before starting a new run."
            if expected - set(pages)
            else "Layout analysis returned unexpected or duplicate page numbers. "
            "Check the service response before starting a new run."
        )
        raise IntegrationError(
            reason,
            error_code="INCOMPLETE_LAYOUT",
            retryable=False,
            diagnostics={"expected_pages": len(expected), "returned_pages": len(original_pages)},
        )
    if pages:
        layout.units = sorted(pages.values(), key=lambda page: page.index)


def _record_item(item: RunItem | None, art: ProcessingArtifact, summary: dict) -> None:
    if item is not None:
        with active_claim(item) if item.attempts else nullcontext():
            item.layout_artifact = art
            item.input_quality = summary
            item.save(update_fields=["layout_artifact", "input_quality", "modified"])


def _publish_layout(
    doc: Document,
    layout: LayoutDocument,
    prepared: PreparedInput,
    *,
    original: Path,
    key: str,
    adapter: str,
    analysis: DIAnalysisConfig,
    run_item: RunItem | None,
) -> None:
    """Publish files before rows, atomically publish units, and clean unpublished files."""
    summary = prepared.summary
    stored_paths: list[str] = []
    published = False
    try:
        source_data: dict[str, Any] | None = None
        if prepared.path != original:
            with prepared.path.open("rb") as source:
                stored, digest = save_file(
                    artifact_path(str(doc.pk), "normalized_image", f"{uuid4().hex}.pdf"), source
                )
            stored_paths.append(stored)
            source_data = {
                "document": doc,
                "kind": ARTIFACT_KIND.normalized_image,
                "stage": "normalization",
                "storage_path": stored,
                "sha256": digest,
                "size_bytes": prepared.path.stat().st_size,
                "cache_key": key if summary.get("status") != "fallback" else "",
                "parameters": {
                    "file_format": prepared.source_format,
                    "source_sha256": doc.sha256,
                    "input_quality": summary,
                    "pages": prepared.page_details,
                    "selected_pages": prepared.selected_pages,
                },
                "page_map": [
                    {"artifact": p["page"] - 1, "original": p["page"] - 1}
                    for p in prepared.page_details
                ],
            }
        payload = layout.model_dump_json().encode("utf-8")
        stored, digest = save_bytes(
            artifact_path(str(doc.pk), "layout", f"{uuid4().hex}.json"), payload
        )
        stored_paths.append(stored)
        # The full layout is the processing source of truth. Page artifacts keep viewer
        # reads bounded without putting a whole OCR document in every web worker's cache.
        unit_paths: dict[int, str] = {}
        for unit in layout.units:
            unit_path, _ = save_bytes(
                artifact_path(str(doc.pk), "layout", f"{uuid4().hex}-unit.json"),
                unit.model_dump_json().encode("utf-8"),
            )
            stored_paths.append(unit_path)
            unit_paths[unit.index] = unit_path
        with (
            transaction.atomic(),
            active_claim(run_item) if run_item is not None and run_item.attempts else nullcontext(),
        ):
            source_art = ProcessingArtifact.objects.create(**source_data) if source_data else None
            art = ProcessingArtifact.objects.create(
                document=doc,
                kind=ARTIFACT_KIND.layout,
                stage="layout",
                storage_path=stored,
                sha256=digest,
                size_bytes=len(payload),
                service_name=layout.service,
                service_version=layout.service_version,
                cache_key=key if summary.get("status") != "fallback" else "",
                source_artifact=source_art,
                parameters={
                    "model_id": layout.model_id,
                    "adapter": adapter,
                    "input_quality": summary,
                    "pages": prepared.page_details,
                    "di_analysis": analysis.model_dump(),
                    "selected_pages": prepared.selected_pages,
                },
                page_map=[{"artifact": i, "original": u.index} for i, u in enumerate(layout.units)],
            )
            SourceUnit.objects.bulk_create(
                [
                    SourceUnit(
                        document=doc,
                        layout_artifact=art,
                        kind=u.kind,
                        index=u.index,
                        label=f"Page {u.number}" if isinstance(u, LayoutPage) else u.name,
                        width=u.width if isinstance(u, LayoutPage) else None,
                        height=u.height if isinstance(u, LayoutPage) else None,
                        unit=(u.unit or "") if isinstance(u, LayoutPage) else "",
                        row_count=None if isinstance(u, LayoutPage) else u.row_count,
                        col_count=None if isinstance(u, LayoutPage) else u.col_count,
                        text_preview=u.content[:1000],
                        layout_storage_path=unit_paths[u.index],
                        service_version=layout.service_version,
                    )
                    for u in layout.units
                ]
            )
            _record_item(run_item, art, summary)
            if doc.file_format in {"docx", "tiff"} and doc.page_count != len(layout.pages):
                doc.page_count = len(layout.pages)
                doc.save(update_fields=["page_count", "modified"])
        published = True
    finally:
        if not published:
            for stored in stored_paths:
                default_storage.delete(stored)


def validate_processing_policy(
    quality: InputQualityConfig,
    analysis: DIAnalysisConfig,
    adapter_key: str,
) -> None:
    from docai.input_quality import validate_input_quality

    validate_input_quality(quality, adapter_key)
    if analysis.ocr_high_resolution and adapter_key != "azure_di":
        raise WorkflowConfigError(
            "High-resolution OCR requires Azure Document Intelligence.",
            errors={
                "di_analysis.ocr_high_resolution": "Select the Azure Document Intelligence layout adapter."
            },
        )


def _log_preparation(doc: Document, prepared: PreparedInput) -> None:
    summary = prepared.summary
    if summary.get("mode") != "adaptive":
        return
    logger.bind(
        document_id=str(doc.pk),
        profile=summary.get("profile"),
        normalization_status=summary.get("status"),
        pages_examined=summary.get("pages_examined", 0),
        pages_adjusted=summary.get("pages_adjusted", 0),
        pages_skipped=summary.get("pages_skipped", 0),
        pages_bypassed=sum(page.get("status") == "bypassed" for page in prepared.page_details),
        duration_ms=summary.get("duration_ms", 0),
        source_bytes=doc.size_bytes,
        prepared_bytes=prepared.path.stat().st_size,
        warning_codes=[warning["code"] for warning in summary.get("warnings", [])],
    ).log(
        "WARNING" if summary.get("status") == "fallback" else "INFO", "Scan preparation completed"
    )


def get_or_build_layout(
    doc: Document,
    adapter_key: str | None = None,
    *,
    input_quality: InputQualityConfig | None = None,
    di_analysis: DIAnalysisConfig | None = None,
    run_item: RunItem | None = None,
    check_cancelled: Callable[[], None] | None = None,
    progress: Callable[[int, int], None] | None = None,
    milestone: Callable[..., None] | None = None,
) -> LayoutDocument:
    from docai.input_quality import prepare_input

    quality = input_quality or InputQualityConfig()
    analysis = di_analysis or DIAnalysisConfig()
    adapter_key = adapter_key or str(settings.DOCAI["LAYOUT_ADAPTER"])
    if check_cancelled is not None:
        check_cancelled()
    validate_processing_policy(quality, analysis, adapter_key)

    def provider_retry(retry_at) -> None:
        if milestone is not None:
            milestone(
                "reading_document",
                "retry_wait" if retry_at is not None else "waiting_for_ocr",
                retry_at=retry_at,
            )

    provider = get_layout_provider_for_format(
        doc.file_format,
        adapter_key,
        retry_observer=provider_retry if milestone is not None else None,
    )
    if run_item is not None and run_item.attempts and hasattr(provider, "bind_recovery"):
        from .checkpoints import Checkpoints

        provider.bind_recovery(Checkpoints(run_item))
    expected_page_count = (
        doc.page_count
        if doc.file_format == "pdf" and doc.page_count > 0
        else 1
        if doc.file_format in {"jpeg", "png"}
        else None
    )
    key = _policy_key(doc, provider.key, quality, analysis)
    cached = (
        doc.artifacts.filter(kind=ARTIFACT_KIND.layout, cache_key=key).order_by("-created").first()
    )
    if cached is not None:
        existing = read_artifact_layout(cached)
        if existing is not None:
            try:
                _complete_pages(
                    existing,
                    cached.parameters.get("pages", []),
                    expected_page_count=expected_page_count,
                )
            except IntegrationError as exc:
                if exc.error_code != "INCOMPLETE_LAYOUT":
                    raise
                # Preserve historical evidence, but rebuild on this run so a tier
                # upgrade can recover without deleting files or changing the policy.
                logger.bind(
                    event="layout_cache_incomplete",
                    service=provider.key,
                    document_id=str(doc.pk),
                    **exc.diagnostics,
                ).warning("Incomplete saved layout ignored; requesting fresh analysis")
            else:
                if milestone is not None:
                    milestone("reading_document", "reusing_layout")
                _record_item(run_item, cached, cached.parameters.get("input_quality", {}))
                logger.bind(
                    event="layout_reused", service=provider.key, units=len(existing.units)
                ).info("Saved layout reused")
                return existing
    if doc.file_format in ("jpeg", "png", "tiff", "docx") and not provider.supports_ocr:
        raise UnsupportedFile(
            f"{doc.file_format.upper()} requires the Azure Document Intelligence layout adapter "
            f"(current adapter '{provider.key}' reads PDF text layers only).",
            error_code="LAYOUT_ADAPTER_UNSUPPORTED",
        )
    if quality.mode == "adaptive":
        if milestone is not None:
            milestone("preparing_scans", "preparing_scans")
        logger.bind(event="normalization_started", stage="normalization").info(
            "Scan preparation started"
        )
    with (
        _source_file(doc) as path,
        prepare_input(
            path,
            source_format=doc.file_format,
            config=quality,
            check_cancelled=check_cancelled,
            progress=progress,
        ) as prepared,
    ):
        if check_cancelled is not None:
            check_cancelled()
        summary = prepared.summary
        _log_preparation(doc, prepared)
        if run_item is not None:
            with active_claim(run_item) if run_item.attempts else nullcontext():
                run_item.input_quality = summary
                run_item.stage = "layout"
                run_item.save(update_fields=["input_quality", "stage", "modified"])
        options: dict[str, Any] = {}
        if prepared.selected_pages is not None:
            options["pages"] = prepared.selected_pages
        if analysis.ocr_high_resolution:
            options["ocr_high_resolution"] = True
        layout_started = time.perf_counter()
        layout_log = logger.bind(service=provider.key, stage="layout", document_id=str(doc.pk))
        layout_log.bind(event="layout_started").info(
            "OCR started" if provider.supports_ocr else "Layout reading started"
        )
        if milestone is not None:
            milestone(
                "reading_document",
                "waiting_for_ocr" if provider.supports_ocr else "reading_document",
            )
        layout = provider.analyze(
            prepared.path,
            document_id=str(doc.id),
            source_format=prepared.source_format,
            **options,
        )
        _complete_pages(layout, prepared.page_details, expected_page_count=expected_page_count)
        if not layout.units or not any(u.content.strip() for u in layout.units):
            raise EmptyFile(
                "Layout analysis returned no content for this document.",
                error_code="EMPTY_LAYOUT",
            )
        if check_cancelled is not None:
            check_cancelled()
        _publish_layout(
            doc,
            layout,
            prepared,
            original=path,
            key=key,
            adapter=provider.key,
            analysis=analysis,
            run_item=run_item,
        )
    layout_log.bind(
        event="layout_completed",
        pages=len(layout.pages),
        sheets=len(layout.sheets),
        chars=sum(len(unit.content) for unit in layout.units),
        duration_ms=round((time.perf_counter() - layout_started) * 1000),
    ).info("OCR completed" if provider.supports_ocr else "Layout reading completed")
    return layout


def unit_layout(doc: Document, unit_index: int, *, run_id: Any = None) -> dict[str, Any] | None:
    artifact = artifact_for_document(doc, run_id)
    if artifact is None:
        return None
    unit_row = units_for_artifact(doc, artifact).filter(index=unit_index).first()
    if unit_row is None:
        return None
    if unit_row.layout_storage_path:
        return cast(dict[str, Any], json.loads(read_bytes(unit_row.layout_storage_path)))
    # Older layouts retain their existing representation; no historical backfill is
    # necessary. All newly published layouts use the bounded path above.
    layout = read_artifact_layout(artifact)
    unit = next((u for u in layout.units if u.index == unit_index), None) if layout else None
    return cast(dict[str, Any], json.loads(unit.model_dump_json())) if unit else None
