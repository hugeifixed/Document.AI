"""Build (once) and load the normalized layout for a document. The layout is
an immutable JSON artifact in storage (not a DB blob) referenced by
SourceUnit rows; DI runs at most once per document."""
from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.db import transaction
from loguru import logger

from docai.adapters.layout.base import get_layout_provider
from docai.adapters.layout.excel import excel_layout
from docai.adapters.storage import artifact_path, local_path, open_file, read_bytes, save_bytes
from docai.exceptions import EmptyFile, UnsupportedFile
from docai.models import ARTIFACT_KIND, SOURCE_KIND, Document, ProcessingArtifact, SourceUnit
from docai.schemas.layout import LayoutDocument, LayoutPage


@contextmanager
def _source_file(doc: Document) -> Iterator[Path]:
    """Yield a local source path and remove any remote-storage staging file."""
    path = local_path(doc.storage_path)
    if path:
        yield Path(path)
        return

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=f".{doc.file_format}",
            delete=False,
        ) as target:  # noqa: SIM117 -- capture the path before opening remote storage
            temporary_path = Path(target.name)
            with open_file(doc.storage_path) as source:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        if temporary_path is None:  # pragma: no cover - NamedTemporaryFile always has a name
            raise RuntimeError("Temporary source file was not created.")
        yield temporary_path
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_layout(doc: Document) -> LayoutDocument | None:
    art = doc.artifacts.filter(kind=ARTIFACT_KIND.layout).order_by("-created").first()
    if not art:
        return None
    return LayoutDocument.model_validate_json(read_bytes(art.storage_path).decode("utf-8"))


def get_or_build_layout(doc: Document, adapter_key: str | None = None) -> LayoutDocument:
    existing = load_layout(doc)
    if existing is not None:
        return existing
    adapter_key = adapter_key or settings.DOCAI["LAYOUT_ADAPTER"]
    with _source_file(doc) as path:
        if doc.file_format in ("xlsx", "xls"):
            layout = excel_layout(path, document_id=str(doc.id), source_format=doc.file_format)
            service_version = layout.service_version
        elif doc.file_format == "txt":
            from docai.adapters.layout.plain_text import text_layout

            layout = text_layout(path, document_id=str(doc.id))
            service_version = ""
        else:
            provider = get_layout_provider(adapter_key)
            if doc.file_format in ("jpeg", "png", "tiff", "docx") and not provider.supports_ocr:
                raise UnsupportedFile(f"{doc.file_format.upper()} requires the Azure Document Intelligence layout adapter "
                                      f"(current adapter '{provider.key}' reads PDF text layers only).",
                                      error_code="LAYOUT_ADAPTER_UNSUPPORTED")
            layout = provider.analyze(path, document_id=str(doc.id), source_format=doc.file_format)
            service_version = layout.service_version
    if not layout.units or not any(u.content.strip() for u in layout.units):
        raise EmptyFile("Layout analysis returned no content for this document.", error_code="EMPTY_LAYOUT")

    payload = layout.model_dump_json().encode("utf-8")
    with transaction.atomic():
        rel = artifact_path(str(doc.id), "layout", "layout.json")
        stored, digest = save_bytes(rel, payload)
        art = ProcessingArtifact.objects.create(document=doc, kind=ARTIFACT_KIND.layout, stage="layout", storage_path=stored,
                                                sha256=digest, size_bytes=len(payload), service_name=layout.service,
                                                service_version=service_version,
                                                parameters={"model_id": layout.model_id, "adapter": adapter_key},
                                                page_map=[{"artifact": i, "original": u.index} for i, u in enumerate(layout.units)])
        SourceUnit.objects.filter(document=doc).delete()
        units = []
        for i, u in enumerate(layout.units):
            if isinstance(u, LayoutPage):
                units.append(SourceUnit(document=doc, kind=SOURCE_KIND.page, index=i, label=f"Page {u.number}",
                                        width=u.width, height=u.height, unit=u.unit, layout_artifact=art,
                                        text_preview=u.content[:1000], service_version=service_version))
            else:
                units.append(SourceUnit(document=doc, kind=SOURCE_KIND.sheet, index=i, label=u.name,
                                        row_count=u.row_count, col_count=u.col_count, layout_artifact=art,
                                        text_preview=u.content[:1000], service_version=service_version))
        SourceUnit.objects.bulk_create(units)
        if doc.file_format == "docx" and doc.page_count != len(layout.pages):
            doc.page_count = len(layout.pages); doc.save(update_fields=["page_count", "modified"])
    logger.bind(document_id=str(doc.id), service=layout.service, units=len(layout.units)).info("layout built")
    return layout


def unit_layout(doc: Document, unit_index: int) -> dict | None:
    layout = load_layout(doc)
    if not layout or unit_index >= len(layout.units):
        return None
    return json.loads(layout.units[unit_index].model_dump_json())
