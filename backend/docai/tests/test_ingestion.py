import io
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from docai.adapters.layout.excel import inspect_xlsx_safety
from docai.exceptions import (
    CorruptFile,
    DuplicateFile,
    EmptyFile,
    ProtectedFile,
    UnsafeWorkbook,
    UnsupportedFile,
    ValidationFailed,
)
from docai.services import ingestion
from docai.services import layouts as layout_service
from docai.synthetic.pdfwriter import write_pdf

pytestmark = pytest.mark.django_db


def test_remote_layout_source_is_streamed_and_temporary_file_is_removed(monkeypatch):
    payload = b"x" * (1024 * 1024 + 1)
    read_sizes: list[int] = []

    class RemoteStream(io.BytesIO):
        def read(self, size=-1):
            read_sizes.append(size)
            return super().read(size)

    source = RemoteStream(payload)
    document = SimpleNamespace(storage_path="remote/document.pdf", file_format="pdf")
    monkeypatch.setattr(layout_service, "local_path", lambda _path: None)
    monkeypatch.setattr(layout_service, "open_file", lambda _path: source)

    with layout_service._source_file(document) as temporary_path:
        assert temporary_path.read_bytes() == payload
        assert temporary_path.exists()

    assert source.closed
    assert read_sizes and -1 not in read_sizes
    assert not temporary_path.exists()


def test_ingest_pdf_creates_document_and_immutable_original(dataset, admin, w2_pdf):
    doc = ingestion.ingest_upload(dataset, w2_pdf.filename, w2_pdf.data, user=admin)
    assert doc.status == "validated" and doc.file_format == "pdf" and doc.page_count == 1
    art = doc.artifacts.get(kind="original")
    assert art.sha256 == doc.sha256 and art.storage_path == doc.storage_path


def test_duplicate_hash_rejected(dataset, admin, w2_pdf):
    ingestion.ingest_upload(dataset, "a.pdf", w2_pdf.data, user=admin)
    with pytest.raises(DuplicateFile):
        ingestion.ingest_upload(dataset, "b.pdf", w2_pdf.data, user=admin)


def test_unsupported_and_corrupt_and_empty(dataset, admin):
    with pytest.raises(UnsupportedFile):
        ingestion.ingest_upload(dataset, "x.exe", b"MZ\x90\x00garbage", user=admin)
    with pytest.raises(CorruptFile):
        ingestion.ingest_upload(dataset, "x.pdf", b"%PDF-1.4 this is not really a pdf", user=admin)
    with pytest.raises(EmptyFile):
        ingestion.ingest_upload(dataset, "x.txt", b"   \n", user=admin)


def test_password_protected_pdf_rejected(dataset, admin):
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter()
    w.append(PdfReader(io.BytesIO(write_pdf([["secret"]]))))
    w.encrypt("pw")
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(ProtectedFile):
        ingestion.ingest_upload(dataset, "p.pdf", buf.getvalue(), user=admin)


def test_extension_spoofing_detected_by_signature(dataset, admin, w2_pdf):
    doc = ingestion.ingest_upload(dataset, "looks_like.png", w2_pdf.data, user=admin)
    assert doc.file_format == "pdf"


def test_excel_safety_refuses_macros(tmp_path, dataset, admin):
    wb = Workbook()
    wb.active["A1"] = "x"
    p = tmp_path / "m.xlsx"
    wb.save(p)
    # inject a vbaProject part into the zip
    import zipfile

    data = p.read_bytes()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.writestr("xl/vbaProject.bin", b"\x00")
    with pytest.raises(UnsafeWorkbook):
        ingestion.ingest_upload(dataset, "m.xlsm.xlsx", out.getvalue(), user=admin)
    p2 = tmp_path / "ok.xlsx"
    wb.save(p2)
    assert inspect_xlsx_safety(p2) == []


def test_office_archive_expansion_is_bounded(dataset, admin, settings):
    import zipfile

    settings.DOCAI["MAX_ARCHIVE_EXPANDED_MB"] = 1
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"<w:t>" + b"x" * (2 * 1024 * 1024))

    with pytest.raises(ValidationFailed) as error:
        ingestion.ingest_upload(dataset, "expands.docx", out.getvalue(), user=admin)
    assert error.value.error_code == "ARCHIVE_LIMIT_EXCEEDED"


def test_upload_endpoint_streams_files_and_reports_accepted_and_rejected(
    api, dataset, w2_pdf, monkeypatch
):
    from django.core.files.uploadedfile import SimpleUploadedFile

    received = []
    ingest = ingestion.ingest_upload

    def capture_upload(dataset, filename, content, **kwargs):
        received.append(content)
        return ingest(dataset, filename, content, **kwargs)

    monkeypatch.setattr(ingestion, "ingest_upload", capture_upload)
    good = SimpleUploadedFile("w2.pdf", w2_pdf.data, content_type="application/pdf")
    bad = SimpleUploadedFile("bad.pdf", b"%PDF-nope", content_type="application/pdf")
    r = api.post(
        f"/api/v1/datasets/{dataset.id}/upload/", {"files": [good, bad]}, format="multipart"
    )
    assert r.status_code == 201
    d = r.json()["data"]
    assert len(d["accepted"]) == 1 and d["rejected"][0]["error_code"] == "CORRUPT_FILE"
    assert len(received) == 2
    assert all(not isinstance(content, bytes) for content in received)
