"""Every LLM request/response is a Pydantic model. Outputs require evidence
and stable source ids; anything that fails validation is an InvalidModelOutput
routed to retry/review — never coerced."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class SourceRef(BaseModel):
    unit_index: int = Field(
        ge=0,
        description="Zero-based page/sheet index in the ORIGINAL document, as printed in its unit header; never chunk-local",
    )
    ids: list[str] = Field(
        default_factory=list, description="Stable ids: p3:w12, p3:t0:r1:c2, s0:B7"
    )
    quote: str = Field(default="", description="Verbatim evidence text (short)")


class SegmentOut(BaseModel):
    start_unit: int = Field(ge=0, description="Original zero-based first unit index")
    end_unit: int = Field(ge=0, description="Original zero-based last unit index")
    category: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: str = ""
    boundary_uncertain: bool = Field(
        default=False,
        description="True for ambiguous starts/continuations, multiple documents on one page, or interleaved documents",
    )
    continuation_of: int | None = Field(
        default=None, description="index of the segment this continues"
    )
    sources: list[SourceRef] = Field(default_factory=list)

    @field_validator("end_unit")
    @classmethod
    def _range(cls, v, info):
        s = info.data.get("start_unit")
        if s is not None and v < s:
            raise ValueError("end_unit must be >= start_unit")
        return v


class SegmentationOut(BaseModel):
    segments: list[SegmentOut] = Field(min_length=1)


class ClassificationOut(BaseModel):
    category: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: str = ""
    sources: list[SourceRef] = Field(default_factory=list)
    alternates: list[str] = Field(default_factory=list)


class FieldOut(BaseModel):
    name: str
    value: str | None = Field(default=None, description="Verbatim; null when not present")
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: str = Field(default="", description="Verbatim quote supporting the value")
    sources: list[SourceRef] = Field(default_factory=list)
    unit_index: int | None = Field(
        default=None,
        ge=0,
        description="Original zero-based unit index, agreeing with sources; never chunk-local",
    )


class ExtractionOut(BaseModel):
    fields: list[FieldOut]

    def as_map(self) -> dict[str, FieldOut]:
        return {f.name: f for f in self.fields}


class GenericKVOut(BaseModel):
    """Default-mode generic extractor: all key/value pairs the model can find."""

    pairs: list[FieldOut]


class StructuredResult(BaseModel):
    """What an LLM adapter returns: parsed model + everything needed for audit."""

    parsed: Any
    raw_response: str
    model_deployment: str
    parameters: dict = Field(default_factory=dict)
    prompt_name: str = ""
    prompt_version: int | None = None
    schema_name: str = ""
    schema_version: int | None = None
    latency_ms: int = 0
    input_chars: int = 0
    attempt: int = 1
