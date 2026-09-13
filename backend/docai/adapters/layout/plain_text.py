"""Plain-text (.txt) layout: built locally from the file itself — no OCR or
layout service is involved for text input, regardless of the configured
adapter. Each line becomes a paragraph/line with a synthetic box so grounding
and labeling behave like any other page."""

from __future__ import annotations

from pathlib import Path

from docai.schemas.layout import LayoutDocument, LayoutPage, Line, Paragraph, Span, Word


def text_layout(path: Path, *, document_id: str) -> LayoutDocument:
    text = path.read_text(encoding="utf-8", errors="replace")
    words: list[Word] = []
    lines: list[Line] = []
    paras: list[Paragraph] = []
    off = 0
    raw_lines = text.splitlines()
    n = max(len(raw_lines), 1)
    for li, line in enumerate(raw_lines):
        y0, y1 = 0.04 + li * (0.9 / n), 0.04 + (li + 1) * (0.9 / n)
        x = 0.05
        lw: list[Word] = []
        for tok in line.split():
            w = 0.008 * len(tok)
            wd = Word(
                id=f"p1:w{len(words)}",
                text=tok,
                span=Span(offset=off + line.find(tok), length=len(tok)),
                polygon=[x, y0, x + w, y0, x + w, y1, x, y1],
            )
            words.append(wd)
            lw.append(wd)
            x += w + 0.008
        if line.strip():
            lines.append(
                Line(
                    id=f"p1:l{len(lines)}",
                    text=line,
                    span=Span(offset=off, length=len(line)),
                    word_ids=[w.id for w in lw],
                    polygon=[0.05, y0, x, y0, x, y1, 0.05, y1],
                )
            )
            paras.append(
                Paragraph(
                    id=f"p1:para{len(paras)}",
                    text=line,
                    span=Span(offset=off, length=len(line)),
                    polygon=lines[-1].polygon,
                )
            )
        off += len(line) + 1
    page = LayoutPage(
        index=0,
        number=1,
        width=8.5,
        height=11,
        unit="inch",
        content=text,
        words=words,
        lines=lines,
        paragraphs=paras,
        reading_order=[p.id for p in paras],
        has_text_layer=True,
    )
    return LayoutDocument(
        document_id=document_id, source_format="txt", service="plain_text", units=[page]
    )


class PlainTextLayout:
    """Layout provider for UTF-8 plain-text documents."""

    key = "plain_text"
    supports_ocr = False

    def analyze(
        self,
        path: Path,
        *,
        document_id: str,
        source_format: str,
        pages: str | None = None,
        ocr_high_resolution: bool = False,
    ) -> LayoutDocument:
        del source_format
        return text_layout(path, document_id=document_id)
