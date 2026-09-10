"""Storage adapter over Django's storage abstraction. Windows-safe naming:
short, ASCII, no reserved names, bounded path length. Swap STORAGES["default"]
to Azure Blob (django-storages) with no code change."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from pathlib import PurePosixPath
from typing import BinaryIO

from django.core.files.base import ContentFile, File
from django.core.files.storage import default_storage

_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_REL_PATH = 180  # leaves room under Windows' 260 with a typical base dir


def safe_name(original: str, max_len: int = 48) -> str:
    stem, dot, ext = original.rpartition(".")
    if not dot:
        stem, ext = original, ""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "file"
    if stem.upper() in _RESERVED:
        stem = f"{stem}_"
    ext = re.sub(r"[^A-Za-z0-9]", "", ext)[:8].lower()
    stem = stem[:max_len]
    return f"{stem}.{ext}" if ext else stem


def artifact_path(document_id: str, kind: str, filename: str) -> str:
    """docs/<first2>/<uuid-no-dashes>/<kind>/<safe>  — short, deterministic."""
    did = str(document_id).replace("-", "")
    rel = PurePosixPath("docs") / did[:2] / did / kind / safe_name(filename)
    s = str(rel)
    assert len(s) <= MAX_REL_PATH, s
    return s


def _chunks(content: File | BinaryIO, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    """Yield bounded chunks and leave a seekable input ready for reuse."""
    content.seek(0)
    try:
        if hasattr(content, "chunks"):
            yield from content.chunks(chunk_size)  # type: ignore[union-attr]
        else:
            while chunk := content.read(chunk_size):
                yield chunk
    finally:
        content.seek(0)


def file_digest(content: File | BinaryIO) -> tuple[str, int]:
    """Return SHA-256 and byte size without materializing the file in memory."""
    sha = hashlib.sha256()
    size = 0
    for chunk in _chunks(content):
        sha.update(chunk)
        size += len(chunk)
    return sha.hexdigest(), size


def save_file(rel_path: str, content: File | BinaryIO, *, digest: str | None = None) -> tuple[str, str]:
    """Stream an immutable file to storage and return (stored path, sha256)."""
    digest = digest or file_digest(content)[0]
    if default_storage.exists(rel_path):
        with default_storage.open(rel_path, "rb") as fh:
            if file_digest(fh)[0] == digest:
                return rel_path, digest
        p = PurePosixPath(rel_path)
        rel_path = str(p.with_name(f"{p.stem}-{digest[:8]}{p.suffix}"))
    content.seek(0)
    stored = default_storage.save(rel_path, content)
    content.seek(0)
    return stored, digest


def save_bytes(rel_path: str, data: bytes) -> tuple[str, str]:
    """Compatibility helper for generated artifacts already held as bytes."""
    return save_file(rel_path, ContentFile(data))


def read_bytes(rel_path: str) -> bytes:
    with default_storage.open(rel_path, "rb") as fh:
        return fh.read()


def open_file(rel_path: str):
    """Return a binary storage stream; callers own and must close it."""
    return default_storage.open(rel_path, "rb")


def local_path(rel_path: str):
    """Filesystem path when the backend supports it (local dev); adapters that
    need a file (pypdf, DI upload) use this or fall back to bytes."""
    try:
        return default_storage.path(rel_path)
    except NotImplementedError:
        return None
