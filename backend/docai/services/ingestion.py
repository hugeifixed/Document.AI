"""Secure ingestion: every check happens BEFORE any Azure or model call.
Type (by signature, not just extension), size, page/sheet count, duplicate
hash, corruption, password protection, empty content, Excel safety. The
original is stored immutably as an artifact; the Document row is created in
`validated` or `rejected` state."""
from __future__ import annotations

import hashlib
import io
import zipfile

from django.conf import settings
from django.db import IntegrityError, transaction
from loguru import logger

from docai.adapters.layout.excel import inspect_xlsx_safety
from docai.adapters.storage import artifact_path, local_path, save_bytes
from docai.exceptions import (CorruptFile, DuplicateFile, EmptyFile, ProtectedFile, UnsafeWorkbook,
                              UnsupportedFile, ValidationFailed)
from docai.models import ARTIFACT_KIND, DOC_STATUS, SUPPORTED_MIME, Dataset, Document, ProcessingArtifact

from . import audit

_SIGNATURES = [
    (b"%PDF", "pdf", "application/pdf"),
    (b"\xff\xd8\xff", "jpeg", "image/jpeg"),
    (b"\x89PNG", "png", "image/png"),
    (b"II*\x00", "tiff", "image/tiff"), (b"MM\x00*", "tiff", "image/tiff"),
    (b"\xd0\xcf\x11\xe0", "xls", "application/vnd.ms-excel"),
]
_EXT_MIME = {ext: mime for mime, ext in SUPPORTED_MIME.items()}


def detect_format(data: bytes, filename: str) -> tuple[str, str]:
    head = data[:8]
    for sig, fmt, mime in _SIGNATURES:
        if head.startswith(sig):
            return fmt, mime
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
        except zipfile.BadZipFile as exc:
            raise CorruptFile() from exc
        if "xl/workbook.xml" in names:
            return "xlsx", _EXT_MIME["xlsx"]
        if "word/document.xml" in names:
            return "docx", _EXT_MIME["docx"]
        raise UnsupportedFile(errors={"file": "ZIP container is not a supported Office document"})
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("txt", "text"):
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise UnsupportedFile(errors={"file": "text files must be UTF-8"}) from None
        return "txt", "text/plain"
    raise UnsupportedFile(errors={"file": f"unrecognized file signature (extension .{ext or '?'})"})


def _inspect(data: bytes, fmt: str) -> dict:
    """Format-specific corruption/protection/empty/page-count checks."""
    cfg = settings.DOCAI
    if fmt == "pdf":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted and not reader.decrypt(""):
                raise ProtectedFile()
            n = len(reader.pages)
        except ProtectedFile:
            raise
        except (PdfReadError, ValueError, OSError, TypeError) as exc:
            raise CorruptFile() from exc
        if n == 0:
            raise EmptyFile()
        if n > cfg["MAX_PAGES"]:
            raise ValidationFailed(f"This file has {n} pages; the limit is {cfg['MAX_PAGES']}.", error_code="TOO_MANY_PAGES")
        return {"page_count": n, "sheet_count": 0}
    if fmt == "xlsx":
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(data)
        from pathlib import Path
        unsafe = inspect_xlsx_safety(Path(tmp.name))
        if unsafe:
            raise UnsafeWorkbook(errors={"unsafe_features": unsafe})
        from openpyxl import load_workbook
        try:
            wb = load_workbook(tmp.name, read_only=True)
            n = len(wb.sheetnames)
            empty = all(ws.max_row in (None, 0, 1) and ws.max_column in (None, 0, 1) and
                        not any(any(c is not None for c in r) for r in ws.iter_rows(values_only=True)) for ws in wb)
        except Exception as exc:  # noqa: BLE001
            raise CorruptFile() from exc
        if n == 0 or empty:
            raise EmptyFile()
        if n > cfg["MAX_SHEETS"]:
            raise ValidationFailed(f"This workbook has {n} sheets; the limit is {cfg['MAX_SHEETS']}.", error_code="TOO_MANY_SHEETS")
        return {"page_count": 0, "sheet_count": n}
    if fmt == "xls":
        import xlrd
        try:
            book = xlrd.open_workbook(file_contents=data)
        except Exception as exc:  # noqa: BLE001
            raise CorruptFile() from exc
        if book.nsheets == 0:
            raise EmptyFile()
        return {"page_count": 0, "sheet_count": book.nsheets}
    if fmt == "docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise CorruptFile() from exc
        if b"<w:t" not in xml:
            raise EmptyFile()
        return {"page_count": 1, "sheet_count": 0}   # DOCX pages are known only after DI layout
    if fmt in ("jpeg", "png", "tiff"):
        return {"page_count": 1, "sheet_count": 0}
    if fmt == "txt":
        if not data.strip():
            raise EmptyFile()
        return {"page_count": 1, "sheet_count": 0}
    raise UnsupportedFile()


def ingest_upload(dataset: Dataset, filename: str, data: bytes, user=None, source: str = "upload") -> Document:
    """Validate, store immutably, create the Document. Raises domain errors for
    rejected files; the caller decides whether to persist a `rejected` row."""
    cfg = settings.DOCAI
    if not data:
        raise EmptyFile()
    if len(data) > cfg["MAX_UPLOAD_MB"] * 1024 * 1024:
        raise ValidationFailed(f"File exceeds the {cfg['MAX_UPLOAD_MB']} MB limit.", error_code="FILE_TOO_LARGE")
    sha = hashlib.sha256(data).hexdigest()
    if Document.objects.filter(dataset=dataset, sha256=sha).exists():
        raise DuplicateFile()
    fmt, mime = detect_format(data, filename)
    counts = _inspect(data, fmt)
    with transaction.atomic():
        try:
            doc = Document.objects.create(dataset=dataset, original_filename=filename[:255], source=source,
                                          mime_type=mime, file_format=fmt, sha256=sha, size_bytes=len(data),
                                          storage_path="", status=DOC_STATUS.uploaded, created_by=user, updated_by=user,
                                          **counts)
        except IntegrityError:
            raise DuplicateFile() from None
        rel = artifact_path(str(doc.id), "original", filename)
        stored, digest = save_bytes(rel, data)
        ProcessingArtifact.objects.create(document=doc, kind=ARTIFACT_KIND.original, stage="ingest", storage_path=stored,
                                          sha256=digest, size_bytes=len(data), service_name="ingestion", created_by=user)
        doc.storage_path = stored
        doc.status = DOC_STATUS.validated
        doc.save(update_fields=["storage_path", "status", "status_changed", "modified"])
    audit.record(user, "document.ingested", doc, after={"format": fmt, "size": len(data), "sha256": sha[:12]})
    logger.bind(document_id=str(doc.id), format=fmt, pages=counts["page_count"]).info("document ingested")
    return doc


def record_rejection(dataset: Dataset, filename: str, data: bytes, error, user=None) -> Document | None:
    """Persist a rejected row so users see why (no original stored for unsafe files)."""
    sha = hashlib.sha256(data).hexdigest() if data else ""
    if not sha or Document.objects.filter(dataset=dataset, sha256=sha).exists():
        return None
    return Document.objects.create(dataset=dataset, original_filename=filename[:255], mime_type="", file_format="",
                                   sha256=sha, size_bytes=len(data), storage_path="", status=DOC_STATUS.rejected,
                                   validation_errors=[{"code": getattr(error, "error_code", "REJECTED"),
                                                       "message": getattr(error, "message", str(error)),
                                                       "errors": getattr(error, "errors", {})}],
                                   created_by=user, updated_by=user)


def original_local_path(doc: Document):
    return local_path(doc.storage_path)
