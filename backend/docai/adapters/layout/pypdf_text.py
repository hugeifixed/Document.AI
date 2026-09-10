"""Local layout provider using ONLY the approved pypdf library: reads the text
layer of text-based PDFs and derives coarse word boxes from text-matrix
positions. This is NOT OCR — image-only pages are reported with
has_text_layer=False and must go to Azure DI. It exists so the platform runs
and tests end-to-end offline on synthetic text PDFs."""
from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from docai.exceptions import CorruptFile, ProtectedFile
from docai.schemas.layout import LayoutDocument, LayoutPage, Line, Paragraph, Span, Word


class PypdfTextLayerLayout:
    key = "pypdf"
    supports_ocr = False

    def analyze(self, path: Path, *, document_id: str, source_format: str) -> LayoutDocument:
        if source_format != "pdf":
            return LayoutDocument(document_id=document_id, source_format=source_format, service="pypdf_text_layer",
                                  warnings=["pypdf adapter only reads PDFs; route this format to azure_di"])
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted and not reader.decrypt(""):
                raise ProtectedFile()
        except ProtectedFile:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CorruptFile() from exc

        pages: list[LayoutPage] = []
        for pi, page in enumerate(reader.pages):
            box = page.mediabox
            w, h = float(box.width), float(box.height)
            items: list[tuple[float, float, str]] = []

            def visitor(text, cm, tm, font_dict, font_size, _items=items):
                t = (text or "").strip()
                if t:
                    _items.append((float(tm[4]), float(tm[5]), t))

            try:
                page.extract_text(visitor_text=visitor)
            except Exception as exc:  # noqa: BLE001
                raise CorruptFile() from exc

            # group into lines by y (descending on page), then order by x
            items.sort(key=lambda it: (-round(it[1], 1), it[0]))
            lines: list[Line] = []
            words: list[Word] = []
            paragraphs: list[Paragraph] = []
            content_parts: list[str] = []
            offset = 0
            cur_y: float | None = None
            cur_line_words: list[Word] = []

            for x, y, t in items:
                if cur_y is None or abs(y - cur_y) > 2.0:
                    offset = _append_line(
                        pi + 1,
                        cur_line_words,
                        lines,
                        paragraphs,
                        content_parts,
                        offset,
                    )
                    cur_line_words = []
                    cur_y = y
                # split the run into words with approximate boxes
                run_w = max(len(t), 1) * 5.0  # coarse: ~5pt per char at default size
                line_off = sum(len(wd.text) + 1 for wd in cur_line_words)
                px = x
                for tok in re.split(r"\s+", t):
                    if not tok:
                        continue
                    tw = len(tok) * (run_w / max(len(t), 1))
                    x0, x1 = px / w, min((px + tw) / w, 1.0)
                    y1 = 1 - (y / h)          # PDF origin bottom-left → normalized top-left
                    y0 = max(0.0, y1 - 12 / h)
                    wid = f"p{pi + 1}:w{len(words)}"
                    words.append(Word(id=wid, text=tok, polygon=[round(x0, 5), round(y0, 5), round(x1, 5), round(y0, 5),
                                                                round(x1, 5), round(y1, 5), round(x0, 5), round(y1, 5)],
                                      span=Span(offset=offset + line_off, length=len(tok))))
                    cur_line_words.append(words[-1])
                    line_off += len(tok) + 1
                    px += tw + 3.0
            _append_line(
                pi + 1,
                cur_line_words,
                lines,
                paragraphs,
                content_parts,
                offset,
            )
            content = "\n".join(content_parts)
            pages.append(LayoutPage(index=pi, number=pi + 1, width=w, height=h, unit="point", content=content,
                                    words=words, lines=lines, paragraphs=paragraphs,
                                    reading_order=[p.id for p in paragraphs], has_text_layer=bool(content.strip())))
        return LayoutDocument(document_id=document_id, source_format="pdf", service="pypdf_text_layer",
                              service_version=_pypdf_version(), units=pages,
                              warnings=[] if all(p.has_text_layer for p in pages) else
                              ["one or more pages have no text layer; OCR via azure_di is required"])


def _append_line(
    page_number: int,
    words: list[Word],
    lines: list[Line],
    paragraphs: list[Paragraph],
    content_parts: list[str],
    offset: int,
) -> int:
    """Append one reconstructed PDF line and return the next content offset."""
    if not words:
        return offset
    text = " ".join(word.text for word in words)
    line = Line(
        id=f"p{page_number}:l{len(lines)}",
        text=text,
        span=Span(offset=offset, length=len(text)),
        word_ids=[word.id for word in words],
        polygon=_union([word.polygon for word in words]),
    )
    lines.append(line)
    paragraphs.append(
        Paragraph(
            id=f"p{page_number}:para{len(paragraphs)}",
            text=text,
            span=Span(offset=offset, length=len(text)),
            polygon=line.polygon,
        )
    )
    content_parts.append(text)
    return offset + len(text) + 1


def _union(polys):
    xs = [v for p in polys for v in p[0::2]]
    ys = [v for p in polys for v in p[1::2]]
    if not xs:
        return []
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return [x0, y0, x1, y0, x1, y1, x0, y1]


def _pypdf_version():
    import pypdf
    return getattr(pypdf, "__version__", "")
