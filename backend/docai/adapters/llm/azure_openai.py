"""Azure-hosted GPT via LangChain with identity-based auth. Structured output
through LangChain's with_structured_output(PydanticModel); validation errors
become InvalidModelOutput. Model swap = settings/config change only."""

from __future__ import annotations

import json
import time

from loguru import logger
from pydantic import ValidationError

from docai.adapters.azure_identity import azure_settings, token_provider, with_retries
from docai.exceptions import InvalidModelOutput
from docai.schemas.llm import StructuredResult

from .base import LLMCall


class AzureOpenAILangChainLLM:
    key = "azure_openai"

    def __init__(self, deployment: str | None = None, parameters: dict | None = None):
        cfg = azure_settings()
        self.endpoint = cfg["AZURE_OPENAI_ENDPOINT"]
        self.api_version = cfg["AZURE_OPENAI_API_VERSION"]
        self.deployment = deployment or cfg["AZURE_OPENAI_DEPLOYMENT"]
        self.parameters = {
            "temperature": 0.0,
            "max_tokens": 4000,
            "timeout_s": cfg["AZURE_TIMEOUT_S"],
            **(parameters or {}),
        }
        if not self.endpoint:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT is not configured")

    def _model(self, deployment: str, params: dict):
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_endpoint=self.endpoint,
            api_version=self.api_version,
            azure_deployment=deployment,
            azure_ad_token_provider=token_provider(),  # no API keys
            temperature=params.get("temperature", 0.0),
            max_completion_tokens=params.get("max_tokens", 4000),
            timeout=params.get("timeout_s", 60),
            max_retries=0,
        )  # retries handled by with_retries

    def invoke(self, call: LLMCall) -> StructuredResult:
        deployment = call.deployment or self.deployment
        params = {**self.parameters, **call.parameters}
        model = self._model(deployment, params)
        structured = model.with_structured_output(call.schema, include_raw=True)
        t0 = time.perf_counter()

        def run():
            return structured.invoke([("system", call.system), ("user", call.user)])

        out = with_retries(run, max_retries=params.get("max_retries", 2))
        latency = int((time.perf_counter() - t0) * 1000)
        raw_msg = out.get("raw")
        raw_text = getattr(raw_msg, "content", "") or json.dumps(
            getattr(raw_msg, "additional_kwargs", {}), default=str
        )
        if out.get("parsing_error") or out.get("parsed") is None:
            logger.bind(deployment=deployment, schema=call.schema.__name__).warning(
                "invalid model output"
            )
            raise InvalidModelOutput(
                errors={
                    "schema": call.schema.__name__,
                    "detail": str(out.get("parsing_error"))[:300],
                }
            )
        parsed = out["parsed"]
        try:
            parsed = call.schema.model_validate(
                parsed if isinstance(parsed, dict) else parsed.model_dump()
            )
        except ValidationError as exc:
            raise InvalidModelOutput(
                errors={"schema": call.schema.__name__, "detail": str(exc)[:300]}
            ) from None
        return StructuredResult(
            parsed=parsed,
            raw_response=raw_text[:20000],
            model_deployment=deployment,
            parameters={k: v for k, v in params.items() if k != "timeout_s"},
            prompt_name=call.prompt_name,
            prompt_version=call.prompt_version,
            schema_name=call.schema_name,
            schema_version=call.schema_version,
            latency_ms=latency,
            input_chars=len(call.system) + len(call.user),
        )
