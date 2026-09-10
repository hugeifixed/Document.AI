"""Strategy interface + shared context. A workflow strategy receives a document
and its normalized layout and returns a DocumentResult; it never touches the
DB, storage, or vendor SDKs directly — services persist, adapters integrate."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from docai.adapters.llm.base import LLMCall, StructuredLLM
from docai.schemas.layout import LayoutDocument


@dataclass
class SegmentResult:
    index: int
    start_unit: int
    end_unit: int
    category: str
    score: float | None
    method: str
    evidence: dict = field(default_factory=dict)
    continuation_of: int | None = None
    sources: list[dict] = field(default_factory=list)


@dataclass
class ClassificationResultData:
    category: str
    score: float | None
    method: str
    rule_score: float | None = None
    matched_evidence: list = field(default_factory=list)
    excluded_evidence: list = field(default_factory=list)
    llm_evidence: str = ""
    sources: list[dict] = field(default_factory=list)
    model_deployment: str = ""
    prompt: tuple[str, int] | None = None
    schema: tuple[str, int] | None = None
    rule_version: str = ""
    segment_index: int | None = None
    review_outcome: str = "pending"


@dataclass
class FieldResultData:
    name: str
    field_type: str
    raw_value: str | None
    normalized_value: str | None
    score: float | None
    source_text: str
    method: str
    strategy: str
    fallback_used: str
    model_deployment: str
    prompt: tuple[str, int] | None
    schema: tuple[str, int] | None
    api_version: str
    validation_status: str
    validation_messages: list
    suggested_correction: str | None
    grounding: dict | None            # {unit_index, word_ids, polygon, offsets, cell_range, method, score}
    review_outcome: str
    segment_index: int | None = None
    candidates: list = field(default_factory=list)
    conflict: bool = False


@dataclass
class DocumentResult:
    segments: list[SegmentResult] = field(default_factory=list)
    classifications: list[ClassificationResultData] = field(default_factory=list)
    fields: list[FieldResultData] = field(default_factory=list)
    raw_responses: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    strategy_used: str = ""
    fallback_used: str | None = None


@dataclass
class PromptRef:
    name: str
    version: int
    system: str
    user_template: str


@dataclass
class WorkflowContext:
    workflow_type: str
    config: Any                               # validated Pydantic config model
    llm: StructuredLLM
    prompts: dict[str, PromptRef]             # stage -> PromptRef
    layout_adapter_key: str
    api_version: str = ""
    schema_versions: dict[str, tuple[str, int]] = field(default_factory=dict)

    def call(self, stage: str, **kw) -> LLMCall:
        p = self.prompts[stage]
        return LLMCall(system=p.system, user=p.user_template.format(**kw.pop("fmt", {})),
                       prompt_name=p.name, prompt_version=p.version,
                       deployment=self.config.model.deployment if hasattr(self.config, "model") else None,
                       parameters={"temperature": getattr(self.config.model, "temperature", 0.0),
                                   "max_tokens": getattr(self.config.model, "max_tokens", 4000),
                                   "max_retries": getattr(self.config.model, "max_retries", 2)}
                       if hasattr(self.config, "model") else {}, **kw)


class WorkflowStrategy(Protocol):
    key: str

    def process_document(self, ctx: WorkflowContext, layout: LayoutDocument) -> DocumentResult: ...


_REGISTRY: dict[str, type] = {}
_LOADED = False


def register(cls):
    _REGISTRY[cls.key] = cls
    return cls


def _load_all():
    global _LOADED
    if not _LOADED:
        from docai.workflows import (classify_structured, classify_unstructured, extract_structured,  # noqa: F401
                                     extract_template, extract_unstructured, unbundle)
        _LOADED = True


def get_strategy(workflow_type: str):
    _load_all()
    cls = _REGISTRY.get(workflow_type)
    if cls is None:
        raise ValueError(f"no strategy for workflow type {workflow_type}")
    return cls()
