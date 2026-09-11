"""StructuredLLM protocol. Every call: system prompt, user content, a Pydantic
output schema, and versions to record. Returns StructuredResult; invalid model
output raises InvalidModelOutput (never coerced)."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    # optional structured hint the MOCK adapter uses to behave deterministically;
    # real adapters ignore it entirely.
    mock_context: dict = field(default_factory=dict)


class StructuredLLM(Protocol):
    key: str

    def invoke(self, call: LLMCall) -> StructuredResult: ...


def get_llm(
    key: str | None = None, *, deployment: str | None = None, parameters: dict | None = None
) -> StructuredLLM:
    key = key or settings.DOCAI["LLM_ADAPTER"]
    if key == "azure_openai":
        from .azure_openai import AzureOpenAILangChainLLM

        return AzureOpenAILangChainLLM(deployment=deployment, parameters=parameters or {})
    if key == "mock":
        from .mock import MockStructuredLLM

        return MockStructuredLLM(deployment=deployment or "mock-deterministic-v1")
    raise ValueError(f"unknown llm adapter {key}")
