"""Secure ingestion: every check happens BEFORE any Azure or model call.
Type (by signature, not just extension), size, page/sheet count, duplicate
hash, corruption, password protection, empty content, Excel safety. The
original is stored immutably as an artifact; the Document row is created in
`validated` or `rejected` state."""

from __future__ import annotations

import zipfile
from typing import BinaryIO, cast

from django.conf import settings
from django.core.files.base import ContentFile, File
from django.db import IntegrityError, transaction
from loguru import logger

from docai.adapters.layout.excel import inspect_xlsx_safety
from docai.adapters.storage import artifact_path, file_digest, local_path, save_file
from docai.exceptions import (
    CorruptFile,
    DuplicateFile,
    EmptyFile,
    ProtectedFile,
    UnsafeWorkbook,
    UnsupportedFile,
    ValidationFailed,
)
from docai.models import (
    ARTIFACT_KIND,
    DOC_STATUS,
    SUPPORTED_MIME,
    Dataset,
    Document,
    ProcessingArtifact,
)

from . import audit

_SIGNATURES = [
    (b"%PDF", "pdf", "application/pdf"),
    (b"\xff\xd8\xff", "jpeg", "image/jpeg"),
    (b"\x89PNG", "png", "image/png"),
    (b"II*\x00", "tiff", "image/tiff"),
    (b"MM\x00*", "tiff", "image/tiff"),
    (b"\xd0\xcf\x11\xe0", "xls", "application/vnd.ms-excel"),
]
_EXT_MIME = {ext: mime for mime, ext in SUPPORTED_MIME.items()}
UploadContent = File | BinaryIO


def _as_content(data: bytes | UploadContent, filename: str) -> UploadContent:
    return ContentFile(data, name=filename) if isinstance(data, bytes) else data


def _rewind(content: UploadContent) -> None:
    content.seek(0)


def _read_all(content: UploadContent) -> bytes:
    _rewind(content)
    try:
        return content.read()
    finally:
        _rewind(content)


def _validate_utf8(content: UploadContent) -> None:
    """Validate a text upload incrementally so large files stay bounded."""
    import codecs

    decoder = codecs.getincrementaldecoder("utf-8")()
    _rewind(content)
    try:
        while chunk := content.read(64 * 1024):
            decoder.decode(chunk)
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        raise UnsupportedFile(errors={"file": "text files must be UTF-8"}) from None
    finally:
        _rewind(content)


def _validate_zip_container(archive: zipfile.ZipFile) -> None:
    """Bound OOXML expansion before any member is decompressed or parsed."""
    cfg = settings.DOCAI
    members = archive.infolist()
    if len(members) > cfg["MAX_ARCHIVE_MEMBERS"]:
        raise ValidationFailed(
            "Office archive contains too many parts.",
            error_code="ARCHIVE_LIMIT_EXCEEDED",
        )

    files = [member for member in members if not member.is_dir()]
    largest = max((member.file_size for member in files), default=0)
    expanded = sum(member.file_size for member in files)
    compressed = sum(max(member.compress_size, 1) for member in files)
    mib = 1024 * 1024
    ratio = expanded / compressed if compressed else 0
    if (
        largest > cfg["MAX_ARCHIVE_MEMBER_MB"] * mib
        or expanded > cfg["MAX_ARCHIVE_EXPANDED_MB"] * mib
        or (expanded > mib and ratio > cfg["MAX_ARCHIVE_COMPRESSION_RATIO"])
    ):
        raise ValidationFailed(
            "Office archive expands beyond the configured safety limit.",
            error_code="ARCHIVE_LIMIT_EXCEEDED",
        )


def detect_format(data: bytes | UploadContent, filename: str) -> tuple[str, str]:
    content = _as_content(data, filename)
    _rewind(content)
    head = content.read(8)
    _rewind(content)
    for sig, fmt, mime in _SIGNATURES:
        if head.startswith(sig):
            return fmt, mime
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(content) as z:
                _validate_zip_container(z)
                names = set(z.namelist())
        except zipfile.BadZipFile as exc:
            raise CorruptFile() from exc
        finally:
            _rewind(content)
        if "xl/workbook.xml" in names:
            return "xlsx", _EXT_MIME["xlsx"]
        if "word/document.xml" in names:
            return "docx", _EXT_MIME["docx"]
        raise UnsupportedFile(errors={"file": "ZIP container is not a supported Office document"})
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("txt", "text"):
        _validate_utf8(content)
        return "txt", "text/plain"
    raise UnsupportedFile(errors={"file": f"unrecognized file signature (extension .{ext or '?'})"})


def _inspect(content: UploadContent, fmt: str) -> dict:
    """Format-specific corruption/protection/empty/page-count checks."""
    cfg = settings.DOCAI
    if fmt == "pdf":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            _rewind(content)
            reader = PdfReader(content)
            if reader.is_encrypted and not reader.decrypt(""):
                raise ProtectedFile()
            n = len(reader.pages)
        except ProtectedFile:
            raise
        except (PdfReadError, ValueError, OSError, TypeError) as exc:
            raise CorruptFile() from exc
        finally:
            _rewind(content)
        if n == 0:
            raise EmptyFile()
        if n > cfg["MAX_PAGES"]:
            raise ValidationFailed(
                f"This file has {n} pages; the limit is {cfg['MAX_PAGES']}.",
                error_code="TOO_MANY_PAGES",
            )
        return {"page_count": n, "sheet_count": 0}
    if fmt == "xlsx":
        unsafe = inspect_xlsx_safety(cast(BinaryIO, content))
        _rewind(content)
        if unsafe:
            raise UnsafeWorkbook(errors={"unsafe_features": unsafe})
        from openpyxl import load_workbook

        wb = None
        try:
            wb = load_workbook(content, read_only=True)
            n = len(wb.sheetnames)
            empty = all(
                ws.max_row in (None, 0, 1)
                and ws.max_column in (None, 0, 1)
                and not any(any(c is not None for c in r) for r in ws.iter_rows(values_only=True))
                for ws in wb
            )
        except Exception as exc:
            raise CorruptFile() from exc
        finally:
            if wb is not None:
                wb.close()
            _rewind(content)
        if n == 0 or empty:
            raise EmptyFile()
        if n > cfg["MAX_SHEETS"]:
            raise ValidationFailed(
                f"This workbook has {n} sheets; the limit is {cfg['MAX_SHEETS']}.",
                error_code="TOO_MANY_SHEETS",
            )
        return {"page_count": 0, "sheet_count": n}
    if fmt == "xls":
        import xlrd

        try:
            temporary_path = getattr(content, "temporary_file_path", None)
            book = (
                xlrd.open_workbook(temporary_path())
                if callable(temporary_path)
                else xlrd.open_workbook(file_contents=_read_all(content))
            )
        except Exception as exc:
            raise CorruptFile() from exc
        if book.nsheets == 0:
            raise EmptyFile()
        return {"page_count": 0, "sheet_count": book.nsheets}
    if fmt == "docx":
        try:
            _rewind(content)
            with zipfile.ZipFile(content) as z:
                xml = z.read("word/document.xml")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise CorruptFile() from exc
        finally:
            _rewind(content)
        if b"<w:t" not in xml:
            raise EmptyFile()
        return {"page_count": 1, "sheet_count": 0}  # DOCX pages are known only after DI layout
    if fmt in ("jpeg", "png", "tiff"):
        return {"page_count": 1, "sheet_count": 0}
    if fmt == "txt":
        has_content = False
        _rewind(content)
        while chunk := content.read(64 * 1024):
            if chunk.strip():
                has_content = True
                break
        _rewind(content)
        if not has_content:
            raise EmptyFile()
        return {"page_count": 1, "sheet_count": 0}
    raise UnsupportedFile()


def ingest_upload(
    dataset: Dataset, filename: str, data: bytes | UploadContent, user=None, source: str = "upload"
) -> Document:
    """Validate, store immutably, create the Document. Raises domain errors for
    rejected files. File objects are hashed, inspected, and stored in bounded
    chunks; the bytes form remains for synthetic documents and generated data."""
    cfg = settings.DOCAI
    content = _as_content(data, filename)
    declared_size = getattr(content, "size", None)
    if declared_size == 0:
        raise EmptyFile()
    if declared_size is not None and declared_size > cfg["MAX_UPLOAD_MB"] * 1024 * 1024:
        raise ValidationFailed(
            f"File exceeds the {cfg['MAX_UPLOAD_MB']} MB limit.", error_code="FILE_TOO_LARGE"
        )
    sha, size = file_digest(content)
    if size == 0:
        raise EmptyFile()
    if size > cfg["MAX_UPLOAD_MB"] * 1024 * 1024:
        raise ValidationFailed(
            f"File exceeds the {cfg['MAX_UPLOAD_MB']} MB limit.", error_code="FILE_TOO_LARGE"
        )
    if Document.objects.filter(dataset=dataset, sha256=sha).exists():
        raise DuplicateFile()
    fmt, mime = detect_format(content, filename)
    counts = _inspect(content, fmt)
    with transaction.atomic():
        try:
            doc = Document.objects.create(
                dataset=dataset,
                original_filename=filename[:255],
                source=source,
                mime_type=mime,
                file_format=fmt,
                sha256=sha,
                size_bytes=size,
                storage_path="",
                status=DOC_STATUS.uploaded,
                created_by=user,
                updated_by=user,
                **counts,
            )
        except IntegrityError:
            raise DuplicateFile() from None
        rel = artifact_path(str(doc.id), "original", filename)
        stored, digest = save_file(rel, content, digest=sha)
        ProcessingArtifact.objects.create(
            document=doc,
            kind=ARTIFACT_KIND.original,
            stage="ingest",
            storage_path=stored,
            sha256=digest,
            size_bytes=size,
            service_name="ingestion",
            created_by=user,
        )
        doc.storage_path = stored
        doc.status = DOC_STATUS.validated
        doc.save(update_fields=["storage_path", "status", "status_changed", "modified"])
    audit.record(
        user, "document.ingested", doc, after={"format": fmt, "size": size, "sha256": sha[:12]}
    )
    logger.bind(document_id=str(doc.id), format=fmt, pages=counts["page_count"]).info(
        "document ingested"
    )
    return doc


def record_rejection(
    dataset: Dataset, filename: str, data: bytes | UploadContent, error, user=None
) -> Document | None:
    """Persist a rejected row so users see why (no original stored for unsafe files)."""
    content = _as_content(data, filename)
    declared_size = getattr(content, "size", None)
    if declared_size is not None and declared_size > settings.DOCAI["MAX_UPLOAD_MB"] * 1024 * 1024:
        return None
    sha, size = file_digest(content)
    if size == 0 or Document.objects.filter(dataset=dataset, sha256=sha).exists():
        return None
    return Document.objects.create(
        dataset=dataset,
        original_filename=filename[:255],
        mime_type="",
        file_format="",
        sha256=sha,
        size_bytes=size,
        storage_path="",
        status=DOC_STATUS.rejected,
        validation_errors=[
            {
                "code": getattr(error, "error_code", "REJECTED"),
                "message": getattr(error, "message", str(error)),
                "errors": getattr(error, "errors", {}),
            }
        ],
        created_by=user,
        updated_by=user,
    )


def original_local_path(doc: Document):
    return local_path(doc.storage_path)
