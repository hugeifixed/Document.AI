"""StructuredLLM protocol. Every call: system prompt, user content, a Pydantic
output schema, and versions to record. Returns StructuredResult; invalid model
output raises InvalidModelOutput (never coerced)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from django.conf import settings
from pydantic import BaseModel

from docai.schemas.llm import StructuredResult


@dataclass
class LLMCall:
    system: str
    user: str
    schema: type[BaseModel]
    prompt_name: str = ""
    prompt_version: int | None = None
    schema_name: str = ""
    schema_version: int | None = None
    deployment: str | None = None
    parameters: dict = field(default_factory=dict)
    stage: str = ""
    chunk_index: int | None = None
    segment_index: int | None = None
    # optional structured hint the MOCK adapter uses to behave deterministically;
    # real adapters ignore it entirely.
    mock_context: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LLMUsage:
    """Provider-neutral, content-free metadata for one model response."""

    provider: str
    model_deployment: str
    model_name: str = ""
    provider_request_id: str = ""
    api_version: str = ""
    input_tokens: int | None = None
    cached_input_tokens: int = 0
    output_tokens: int | None = None
    reasoning_tokens: int = 0
    total_tokens: int | None = None
    latency_ms: int = 0
    outcome: str = "succeeded"
    finish_reason: str = ""
    safety_outcome: str = "unknown"


LLMUsageObserver = Callable[[LLMCall, LLMUsage], None]
LLMRetryObserver = Callable[[str, datetime | None], None]


class StructuredLLM(Protocol):
    key: str

    def invoke(self, call: LLMCall) -> StructuredResult: ...


def get_llm(
    key: str | None = None,
    *,
    deployment: str | None = None,
    parameters: dict | None = None,
    usage_observer: LLMUsageObserver | None = None,
    retry_observer: LLMRetryObserver | None = None,
) -> StructuredLLM:
    key = key or str(settings.DOCAI["LLM_ADAPTER"])
    if key == "azure_openai":
        from .azure_openai import AzureOpenAILangChainLLM

        return AzureOpenAILangChainLLM(
            deployment=deployment,
            parameters=parameters or {},
            usage_observer=usage_observer,
            retry_observer=retry_observer,
        )
    if key == "mock":
        from .mock import MockStructuredLLM

        return MockStructuredLLM(deployment=deployment or "mock-deterministic-v1")
    raise ValueError(f"unknown llm adapter {key}")
