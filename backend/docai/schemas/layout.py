"""Normalized layout representation. Azure Document Intelligence Layout and
Excel workbooks are both normalized into this one model so every downstream
stage (preservation, chunking, grounding, labeling) is source-agnostic.

Nothing from DI is discarded: words/lines/paragraphs (with roles), tables with
cell coordinates and spans, selection marks, sections, reading order, page
dimensions + unit, and the service/API version all survive. Stable ids let the
LLM cite sources it can be held to:  p3:w12  p3:l4  p3:t0:r2:c1  s1:B7
Polygons are normalized to 0-1 fractions of the page so PDF.js (points) and
DI (inches/pixels) can be compared without unit gymnastics."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field


class Span(BaseModel):
    offset: int = Field(ge=0, description="Character offset into the unit's content string")
    length: int = Field(ge=0)


class Word(BaseModel):
    id: str
    text: str
    polygon: list[float] = Field(
        default_factory=list, description="[x1,y1,x2,y2,x3,y3,x4,y4] normalized 0-1"
    )
    span: Span | None = None
    confidence: float | None = None


class Line(BaseModel):
    id: str
    text: str
    polygon: list[float] = Field(default_factory=list)
    span: Span | None = None
    word_ids: list[str] = Field(default_factory=list)


class Paragraph(BaseModel):
    id: str
    text: str
    role: str | None = Field(
        default=None,
        description="title|sectionHeading|pageHeader|pageFooter|footnote|formulaBlock|null",
    )
    polygon: list[float] = Field(default_factory=list)
    span: Span | None = None


class TableCell(BaseModel):
    id: str
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    kind: str = Field(
        default="content", description="content|columnHeader|rowHeader|stubHead|description"
    )
    text: str
    polygon: list[float] = Field(default_factory=list)
    span: Span | None = None


class Table(BaseModel):
    id: str
    row_count: int
    col_count: int
    cells: list[TableCell]
    polygon: list[float] = Field(default_factory=list)
    caption: str | None = None


class SelectionMark(BaseModel):
    id: str
    state: Literal["selected", "unselected"]
    polygon: list[float] = Field(default_factory=list)
    span: Span | None = None


class SheetCell(BaseModel):
    id: str
    ref: str = Field(description="A1-style reference")
    row: int
    col: int
    value: str | None
    formula: str | None = None
    merged_range: str | None = None
    number_format: str | None = None


class LayoutPage(BaseModel):
    kind: Literal["page"] = "page"
    index: int = Field(ge=0, description="0-based page index in the ORIGINAL document")
    number: int = Field(ge=1, description="1-based page number")
    width: float | None = None
    height: float | None = None
    unit: str | None = Field(default=None, description="inch|pixel|point")
    angle: float | None = None
    content: str = Field(default="", description="Full page text; spans index into this")
    words: list[Word] = Field(default_factory=list)
    lines: list[Line] = Field(default_factory=list)
    paragraphs: list[Paragraph] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    selection_marks: list[SelectionMark] = Field(default_factory=list)
    reading_order: list[str] = Field(
        default_factory=list, description="Ordered paragraph/table ids"
    )
    has_text_layer: bool = True
    excluded_from_analysis: bool = False


class LayoutSheet(BaseModel):
    kind: Literal["sheet"] = "sheet"
    index: int
    name: str
    row_count: int
    col_count: int
    cells: list[SheetCell] = Field(default_factory=list)
    merged_ranges: list[str] = Field(default_factory=list)
    tables: list[str] = Field(default_factory=list, description="Named table ranges if present")
    reading_order: list[str] = Field(default_factory=list, description="Row-major cell ids")
    content: str = Field(default="", description="Row-major text rendering")


class LayoutDocument(BaseModel):
    document_id: str
    source_format: str
    service: str = Field(
        description="azure_document_intelligence|pypdf_text_layer|openpyxl|fixture"
    )
    service_version: str = ""
    model_id: str | None = Field(default=None, description="e.g. prebuilt-layout")
    units: Sequence[LayoutPage | LayoutSheet] = Field(default_factory=list)
    sections: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def pages(self) -> list[LayoutPage]:
        return [u for u in self.units if isinstance(u, LayoutPage)]

    @property
    def sheets(self) -> list[LayoutSheet]:
        return [u for u in self.units if isinstance(u, LayoutSheet)]

    def unit_text(self, index: int) -> str:
        return self.units[index].content if 0 <= index < len(self.units) else ""
