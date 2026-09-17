"""Azure AI Document Intelligence — prebuilt-layout — normalized losslessly.
Accepts PDF, images, DOCX, XLSX/XLS (the 2024-11-30 API ingests Office files
natively, so no conversion library is needed)."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

from docai.adapters.azure_identity import (
    azure_settings,
    azure_transport_options,
    document_intelligence_credential,
    with_retries,
)
from docai.exceptions import IntegrationError
from docai.input_quality.pdf_inspection import text_layers
from docai.schemas.layout import (
    LayoutDocument,
    LayoutPage,
    Line,
    Paragraph,
    SelectionMark,
    Span,
    Table,
    TableCell,
    Word,
)


def _norm_poly(poly, width, height):
    """DI polygons are [x1,y1,...] in page units; normalize to 0-1."""
    if not poly or not width or not height:
        return []
    out = []
    for i, v in enumerate(poly):
        out.append(round(v / (width if i % 2 == 0 else height), 5))
    return out


def _span(spans):
    if not spans:
        return None
    s = spans[0]
    return Span(offset=s.offset, length=s.length)


class AzureDocumentIntelligenceLayout:
    key = "azure_di"
    supports_ocr = True

    def __init__(self, *, retry_observer: Callable[[datetime | None], None] | None = None):
        cfg = azure_settings()
        self.endpoint = cfg["AZURE_DI_ENDPOINT"]
        self.api_version = cfg["AZURE_DI_API_VERSION"]
        self.timeout = cfg["AZURE_TIMEOUT_S"]
        self.retry_observer = retry_observer
        if not self.endpoint:
            raise RuntimeError("AZURE_DI_ENDPOINT is not configured")

    def _client(self):
        from azure.ai.documentintelligence import DocumentIntelligenceClient

        return DocumentIntelligenceClient(
            endpoint=self.endpoint,
            credential=document_intelligence_credential(),
            api_version=self.api_version,
            **azure_transport_options(),
        )

    def analyze(
        self,
        path: Path,
        *,
        document_id: str,
        source_format: str,
        pages: str | None = None,
        ocr_high_resolution: bool = False,
    ) -> LayoutDocument:
        features = ["keyValuePairs"] if source_format in ("pdf", "jpeg", "png", "tiff") else []
        if features and ocr_high_resolution:
            features.append("ocrHighResolution")
        result = self._analyze_result(path, features=features, pages=pages)
        layout = self.normalize(result, document_id=document_id, source_format=source_format)
        if source_format == "pdf":
            layers = text_layers(path)
            for page in layout.pages:
                page.has_text_layer = layers.get(page.index, False)
        return layout

    def bind_recovery(self, recovery) -> None:
        """Accept a service-owned store; the adapter never imports ORM/storage code."""
        self.recovery = recovery

    def _operation_id(self, location: str) -> str:
        endpoint, supplied = urlsplit(self.endpoint), urlsplit(location)
        prefix = (
            endpoint.path.rstrip("/")
            + "/documentintelligence/documentModels/prebuilt-layout/analyzeResults/"
        )
        query = parse_qs(supplied.query)
        if (
            supplied.scheme != endpoint.scheme
            or supplied.netloc != endpoint.netloc
            or not supplied.path.startswith(prefix)
            or supplied.fragment
            or query.get("api-version") != [self.api_version]
        ):
            raise IntegrationError(
                "Invalid OCR operation reference.",
                error_code="OCR_OPERATION_INVALID",
                retryable=False,
            )
        try:
            return str(UUID(supplied.path[len(prefix) :]))
        except ValueError:
            raise IntegrationError(
                "Invalid OCR operation reference.",
                error_code="OCR_OPERATION_INVALID",
                retryable=False,
            ) from None

    def _analyze_result(self, path: Path, *, features: list[str], pages: str | None):
        from azure.ai.documentintelligence.models import AnalyzeResult
        from azure.core.exceptions import HttpResponseError
        from azure.core.rest import HttpRequest
        from loguru import logger

        # Persist only a validated UUID, never a continuation token (some SDKs
        # deserialize those with pickle) or a caller-controlled fetch URL.
        with path.open("rb") as source:
            source_hash = hashlib.file_digest(source, "sha256").hexdigest()
        policy = {
            "source": source_hash,
            "endpoint": self.endpoint.rstrip("/"),
            "api_version": self.api_version,
            "model": "prebuilt-layout",
            "features": features,
            "pages": pages,
        }
        key = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
        recovery = getattr(self, "recovery", None)
        saved = recovery.read_operation(key) if recovery is not None else None
        state: dict[str, Any] = saved or {"resubmissions": 0}
        client = self._client()

        try:

            def check():
                if recovery is not None:
                    recovery.check()

            def save():
                if recovery is not None:
                    recovery.save_operation(key, dict(state))

            def submit():
                check()

                def accepted(response):
                    location = response.http_response.headers.get("Operation-Location", "")
                    if response.http_response.status_code == 202:
                        state["result_id"] = self._operation_id(location)
                        save()

                # Disable automatic submission retries: an uncertain HTTP outcome may
                # already have incurred provider work. Recovery retries GETs separately.
                with path.open("rb") as source:
                    client.begin_analyze_document(
                        "prebuilt-layout",
                        source,
                        content_type="application/octet-stream",
                        features=features or None,
                        **({"pages": pages} if pages is not None else {}),
                        polling=False,
                        raw_response_hook=accepted,
                        retry_total=0,
                    )
                if not state.get("result_id"):
                    raise IntegrationError(
                        "OCR submission returned no operation reference.",
                        error_code="OCR_OPERATION_INVALID",
                        retryable=False,
                    )

            if not state.get("result_id"):
                with_retries(submit, max_retries=0)
            deadline = time.monotonic() + self.timeout * 10
            while True:
                check()
                try:
                    result_id = str(UUID(state["result_id"]))
                except (ValueError, TypeError, KeyError):
                    raise IntegrationError(
                        "Invalid saved OCR operation reference.",
                        error_code="OCR_OPERATION_INVALID",
                        retryable=False,
                    ) from None
                url = (
                    self.endpoint.rstrip("/")
                    + "/documentintelligence/documentModels/prebuilt-layout/analyzeResults/"
                    + result_id
                    + "?"
                    + urlencode({"api-version": self.api_version})
                )

                def poll(url=url):
                    check()
                    response = client.send_request(HttpRequest("GET", url))
                    try:
                        if response.status_code in (404, 410):
                            return None, 0
                        if response.status_code >= 400:
                            raise HttpResponseError(response=response)
                        return response.json(), response.headers.get("Retry-After", "2")
                    finally:
                        response.close()

                with logger.contextualize(
                    stage="layout", service=self.key, model="prebuilt-layout"
                ):
                    observer = getattr(self, "retry_observer", None)
                    body, wait = (
                        with_retries(poll, retry_observer=observer)
                        if observer is not None
                        else with_retries(poll)
                    )
                if body is None:
                    if state.get("resubmissions", 0) >= 1:
                        raise IntegrationError(
                            "OCR operation expired again; start a new run.",
                            error_code="OCR_OPERATION_EXPIRED",
                            retryable=False,
                        )
                    state = {
                        "resubmissions": 1,
                        "previous_result_id": result_id,
                        "resubmit_reason": "operation_unavailable",
                    }
                    save()  # Consume the single recovery budget before another POST.
                    logger.bind(
                        event="ocr_operation_resubmitted", reason="operation_unavailable"
                    ).warning("Saved OCR operation unavailable; resubmitting once")
                    with_retries(submit, max_retries=0)
                    continue
                status = body.get("status", "").lower()
                if status == "succeeded":
                    return AnalyzeResult(body["analyzeResult"])
                if status in {"failed", "canceled", "cancelled"}:
                    raise IntegrationError(
                        "Document analysis failed at the OCR provider.",
                        error_code="OCR_ANALYSIS_FAILED",
                        retryable=False,
                    )
                if status not in {"running", "notstarted"}:
                    raise IntegrationError(
                        "OCR provider returned an invalid operation status.",
                        error_code="OCR_OPERATION_INVALID",
                        retryable=False,
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise IntegrationError(
                        "OCR is still processing; retry resumes the saved operation.",
                        error_code="OCR_POLL_TIMEOUT",
                        retryable=True,
                    )
                try:
                    delay = min(10, max(0.1, float(wait)))
                except (ValueError, TypeError):
                    delay = 2
                time.sleep(min(delay, remaining))

        finally:
            client.close()

    # ---------------------------------------------------------------- normalize
    def normalize(self, result, *, document_id: str, source_format: str) -> LayoutDocument:
        content = result.content or ""
        pages: list[LayoutPage] = []
        by_page_paragraphs: dict[int, list[Paragraph]] = {}
        by_page_tables: dict[int, list[Table]] = {}

        for pi, para in enumerate(result.paragraphs or []):
            br = (para.bounding_regions or [None])[0]
            pnum = br.page_number if br else 1
            by_page_paragraphs.setdefault(pnum, []).append(
                Paragraph(
                    id=f"p{pnum}:para{pi}",
                    text=para.content or "",
                    role=getattr(para, "role", None),
                    polygon=[],
                    span=_span(para.spans),
                )
            )
        for ti, table in enumerate(result.tables or []):
            br = (table.bounding_regions or [None])[0]
            pnum = br.page_number if br else 1
            cells = []
            for c in table.cells or []:
                cells.append(
                    TableCell(
                        id=f"p{pnum}:t{ti}:r{c.row_index}:c{c.column_index}",
                        row=c.row_index,
                        col=c.column_index,
                        row_span=c.row_span or 1,
                        col_span=c.column_span or 1,
                        kind=c.kind or "content",
                        text=c.content or "",
                        polygon=[],
                        span=_span(c.spans),
                    )
                )
            by_page_tables.setdefault(pnum, []).append(
                Table(
                    id=f"p{pnum}:t{ti}",
                    row_count=table.row_count,
                    col_count=table.column_count,
                    cells=cells,
                )
            )

        for page in result.pages or []:
            pnum = page.page_number
            w, h = page.width, page.height
            words = [
                Word(
                    id=f"p{pnum}:w{i}",
                    text=wd.content,
                    polygon=_norm_poly(wd.polygon, w, h),
                    span=Span(offset=wd.span.offset, length=wd.span.length) if wd.span else None,
                    confidence=wd.confidence,
                )
                for i, wd in enumerate(page.words or [])
            ]
            lines = [
                Line(
                    id=f"p{pnum}:l{i}",
                    text=ln.content,
                    polygon=_norm_poly(ln.polygon, w, h),
                    span=_span(ln.spans),
                )
                for i, ln in enumerate(page.lines or [])
            ]
            marks = [
                SelectionMark(
                    id=f"p{pnum}:sm{i}",
                    state=sm.state,
                    polygon=_norm_poly(sm.polygon, w, h),
                    span=Span(offset=sm.span.offset, length=sm.span.length) if sm.span else None,
                )
                for i, sm in enumerate(page.selection_marks or [])
            ]
            # page content = slice of global content by the page's spans
            ptext = (
                "".join(content[s.offset : s.offset + s.length] for s in (page.spans or [])) or ""
            )
            # rebase spans to page-local offsets
            base = page.spans[0].offset if page.spans else 0
            for coll in (words, lines, marks):
                for it in coll:
                    if it.span:
                        it.span = Span(offset=max(0, it.span.offset - base), length=it.span.length)
            paras = by_page_paragraphs.get(pnum, [])
            for p in paras:
                if p.span:
                    p.span = Span(offset=max(0, p.span.offset - base), length=p.span.length)
            tables = by_page_tables.get(pnum, [])
            for t in tables:
                for c in t.cells:
                    if c.span:
                        c.span = Span(offset=max(0, c.span.offset - base), length=c.span.length)
            # reading order: paragraphs and tables interleaved by span offset
            order = sorted(
                [(p.span.offset if p.span else 0, p.id) for p in paras]
                + [(min([c.span.offset for c in t.cells if c.span] or [0]), t.id) for t in tables]
            )
            pages.append(
                LayoutPage(
                    index=pnum - 1,
                    number=pnum,
                    width=w,
                    height=h,
                    unit=page.unit,
                    angle=page.angle,
                    content=ptext,
                    words=words,
                    lines=lines,
                    paragraphs=paras,
                    tables=tables,
                    selection_marks=marks,
                    reading_order=[i for _, i in order],
                    # DI words are OCR/layout results; the source's native PDF text
                    # layer is assessed separately, never inferred from DI output.
                    has_text_layer=False,
                )
            )

        return LayoutDocument(
            document_id=document_id,
            source_format=source_format,
            service="azure_document_intelligence",
            service_version=self.api_version,
            model_id=getattr(result, "model_id", "prebuilt-layout"),
            units=pages,
            sections=[
                {
                    "spans": [{"offset": s.offset, "length": s.length} for s in sec.spans or []],
                    "elements": list(sec.elements or []),
                }
                for sec in (result.sections or [])
            ],
        )
