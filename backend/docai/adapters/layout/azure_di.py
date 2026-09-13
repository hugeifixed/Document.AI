"""Azure AI Document Intelligence — prebuilt-layout — normalized losslessly.
Accepts PDF, images, DOCX, XLSX/XLS (the 2024-11-30 API ingests Office files
natively, so no conversion library is needed)."""

from __future__ import annotations

from pathlib import Path

from docai.adapters.azure_identity import (
    azure_settings,
    document_intelligence_credential,
    with_retries,
)
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

    def __init__(self):
        cfg = azure_settings()
        self.endpoint = cfg["AZURE_DI_ENDPOINT"]
        self.api_version = cfg["AZURE_DI_API_VERSION"]
        self.timeout = cfg["AZURE_TIMEOUT_S"]
        if not self.endpoint:
            raise RuntimeError("AZURE_DI_ENDPOINT is not configured")

    def _client(self):
        from azure.ai.documentintelligence import DocumentIntelligenceClient

        return DocumentIntelligenceClient(
            endpoint=self.endpoint,
            credential=document_intelligence_credential(),
            api_version=self.api_version,
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
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

        features = ["keyValuePairs"] if source_format in ("pdf", "jpeg", "png", "tiff") else []
        if features and ocr_high_resolution:
            features.append("ocrHighResolution")

        def call():
            with open(path, "rb") as fh:
                poller = self._client().begin_analyze_document(
                    "prebuilt-layout",
                    AnalyzeDocumentRequest(bytes_source=fh.read()),
                    features=features or None,
                    **({"pages": pages} if pages is not None else {}),
                )
            return poller.result(timeout=self.timeout * 10)

        from loguru import logger

        with logger.contextualize(stage="layout", service=self.key, model="prebuilt-layout"):
            result = with_retries(call)
        layout = self.normalize(result, document_id=document_id, source_format=source_format)
        if source_format == "pdf":
            layers = text_layers(path)
            for page in layout.pages:
                page.has_text_layer = layers.get(page.index, False)
        return layout

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
