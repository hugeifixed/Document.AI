import io
from types import SimpleNamespace
from typing import Any, cast

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
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

    with layout_service._source_file(cast(Any, document)) as temporary_path:
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


def test_ingest_or_reuse_reports_existing_document(dataset, admin, w2_pdf):
    first = ingestion.ingest_or_reuse_upload(dataset, "first.pdf", w2_pdf.data, user=admin)
    second = ingestion.ingest_or_reuse_upload(dataset, "renamed.pdf", w2_pdf.data, user=admin)

    assert first.reused is False
    assert second.reused is True
    assert second.document.pk == first.document.pk
    assert second.document.original_filename == "first.pdf"


def test_ingest_or_reuse_resolves_constraint_race(dataset, admin, w2_pdf, monkeypatch):
    create_document = ingestion._create_document

    def concurrent_winner(*args, **kwargs):
        create_document(*args, **kwargs)
        raise DuplicateFile() from None

    monkeypatch.setattr(ingestion, "_create_document", concurrent_winner)
    result = ingestion.ingest_or_reuse_upload(dataset, "raced.pdf", w2_pdf.data, user=admin)

    assert result.reused is True
    assert result.document.original_filename == "raced.pdf"


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
    ws = wb.active
    assert ws is not None
    ws["A1"] = "x"
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
    ingest = ingestion.ingest_or_reuse_upload

    def capture_upload(dataset, filename, content, **kwargs):
        received.append(content)
        return ingest(dataset, filename, content, **kwargs)

    monkeypatch.setattr(ingestion, "ingest_or_reuse_upload", capture_upload)
    good = SimpleUploadedFile("w2.pdf", w2_pdf.data, content_type="application/pdf")
    bad = SimpleUploadedFile("bad.pdf", b"%PDF-nope", content_type="application/pdf")
    r = api.post(
        f"/api/v1/datasets/{dataset.id}/upload/", {"files": [good, bad]}, format="multipart"
    )
    assert r.status_code == 201
    d = r.json()["data"]
    assert len(d["accepted"]) == 1 and d["rejected"][0]["error_code"] == "CORRUPT_FILE"
    assert d["reused_document_ids"] == []
    assert len(received) == 2
    assert all(not isinstance(content, bytes) for content in received)


def test_upload_endpoint_reuses_same_dataset_content(api, dataset, admin, w2_pdf):
    document = ingestion.ingest_upload(dataset, "original.pdf", w2_pdf.data, user=admin)
    response = api.post(
        f"/api/v1/datasets/{dataset.id}/upload/",
        {"files": [SimpleUploadedFile("renamed.pdf", w2_pdf.data)]},
        format="multipart",
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert [item["id"] for item in payload["accepted"]] == [str(document.pk)]
    assert payload["reused_document_ids"] == [str(document.pk)]
    assert payload["rejected"] == []


def test_upload_endpoint_handles_same_batch_duplicates(api, dataset, w2_pdf):
    response = api.post(
        f"/api/v1/datasets/{dataset.id}/upload/",
        {
            "files": [
                SimpleUploadedFile("first.pdf", w2_pdf.data),
                SimpleUploadedFile("second.pdf", w2_pdf.data),
            ]
        },
        format="multipart",
    )

    assert response.status_code == 201
    payload = response.json()["data"]
    assert len(payload["accepted"]) == 2
    assert payload["accepted"][0]["id"] == payload["accepted"][1]["id"]
    assert payload["reused_document_ids"] == [payload["accepted"][0]["id"]]


def test_upload_endpoint_mixes_created_reused_and_rejected(api, dataset, admin, w2_pdf):
    existing = ingestion.ingest_upload(dataset, "original.pdf", w2_pdf.data, user=admin)
    response = api.post(
        f"/api/v1/datasets/{dataset.id}/upload/",
        {
            "files": [
                SimpleUploadedFile("reused.pdf", w2_pdf.data),
                SimpleUploadedFile("new.txt", b"new accepted content"),
                SimpleUploadedFile("bad.exe", b"not supported"),
            ]
        },
        format="multipart",
    )

    assert response.status_code == 201
    payload = response.json()["data"]
    assert len(payload["accepted"]) == 2
    assert payload["reused_document_ids"] == [str(existing.pk)]
    assert payload["rejected"][0]["error_code"] == "UNSUPPORTED_FILE"


def test_upload_endpoint_replays_previous_rejection_without_duplicate_row(api, dataset):
    url = f"/api/v1/datasets/{dataset.id}/upload/"

    def rejected_upload():
        return SimpleUploadedFile("bad.exe", b"not supported")

    first = api.post(url, {"files": [rejected_upload()]}, format="multipart")
    second = api.post(url, {"files": [rejected_upload()]}, format="multipart")

    assert first.status_code == second.status_code == 422
    assert first.json()["data"]["rejected"] == second.json()["data"]["rejected"]
    assert second.json()["data"]["reused_document_ids"] == []
    assert dataset.documents.count() == 1
