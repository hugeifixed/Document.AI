"""Deterministic layouts for tests: loads a JSON LayoutDocument stored next to
the input file (<name>.layout.json), or synthesizes one from a .txt file."""

from __future__ import annotations

import json
from pathlib import Path

from docai.schemas.layout import LayoutDocument, LayoutPage, Paragraph, Span, Word


class FixtureLayout:
    key = "fixture"
    supports_ocr = True  # pretends to, for image fixtures

    def analyze(self, path: Path, *, document_id: str, source_format: str) -> LayoutDocument:
        side = path.with_suffix(path.suffix + ".layout.json")
        if side.exists():
            data = json.loads(side.read_text(encoding="utf-8"))
            data["document_id"] = document_id
            return LayoutDocument.model_validate(data)
        text = path.read_text(encoding="utf-8", errors="replace") if source_format == "txt" else ""
        words, paras, off = [], [], 0
        for li, line in enumerate(text.splitlines()):
            paras.append(
                Paragraph(id=f"p1:para{li}", text=line, span=Span(offset=off, length=len(line)))
            )
            x = 0.05
            for tok in line.split():
                words.append(
                    Word(
                        id=f"p1:w{len(words)}",
                        text=tok,
                        span=Span(offset=off + line.find(tok), length=len(tok)),
                        polygon=[
                            x,
                            0.05 + li * 0.02,
                            x + 0.01 * len(tok),
                            0.05 + li * 0.02,
                            x + 0.01 * len(tok),
                            0.07 + li * 0.02,
                            x,
                            0.07 + li * 0.02,
                        ],
                    )
                )
                x += 0.01 * len(tok) + 0.01
            off += len(line) + 1
        page = LayoutPage(
            index=0,
            number=1,
            width=8.5,
            height=11,
            unit="inch",
            content=text,
            words=words,
            paragraphs=paras,
            reading_order=[p.id for p in paras],
            has_text_layer=True,
        )
        return LayoutDocument(
            document_id=document_id, source_format=source_format, service="fixture", units=[page]
        )
