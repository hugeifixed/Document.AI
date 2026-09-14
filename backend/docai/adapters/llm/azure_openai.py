"""Azure-hosted GPT via LangChain with identity or optional local key auth. Structured output
through LangChain's with_structured_output(PydanticModel); validation errors
become InvalidModelOutput. Model swap = settings/config change only."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

from loguru import logger
from pydantic import ValidationError

from docai.adapters.azure_identity import (
    azure_error_diagnostics,
    azure_openai_authentication,
    azure_settings,
    with_retries,
)
from docai.exceptions import IntegrationError, InvalidModelOutput
from docai.schemas.llm import StructuredResult

from .base import LLMCall, LLMRetryObserver, LLMUsage, LLMUsageObserver


class AzureOpenAILangChainLLM:
    key = "azure_openai"

    def __init__(
        self,
        deployment: str | None = None,
        parameters: dict | None = None,
        usage_observer: LLMUsageObserver | None = None,
        retry_observer: LLMRetryObserver | None = None,
    ):
        cfg = azure_settings()
        self.endpoint = cfg["AZURE_OPENAI_ENDPOINT"].strip()
        try:
            endpoint = urlsplit(self.endpoint)
            valid_root = (
                endpoint.scheme in {"http", "https"}
                and bool(endpoint.hostname)
                and endpoint.path in {"", "/"}
                and not (
                    endpoint.query or endpoint.fragment or endpoint.username or endpoint.password
                )
            )
        except ValueError:
            valid_root = False
        if not valid_root:
            raise IntegrationError(
                "AZURE_OPENAI_ENDPOINT must be the resource root URL, such as "
                "https://resource.openai.azure.com/, without an API path or query string.",
                error_code="AZURE_ENDPOINT_INVALID",
                retryable=False,
            )
        self.api_version = cfg["AZURE_OPENAI_API_VERSION"]
        self.deployment = deployment or cfg["AZURE_OPENAI_DEPLOYMENT"]
        self.parameters = {
            "temperature": 0.0,
            "max_tokens": 4000,
            "timeout_s": cfg["AZURE_TIMEOUT_S"],
            **(parameters or {}),
        }
        self.usage_observer = usage_observer
        self.retry_observer = retry_observer

    @staticmethod
    def _detail_total(details: dict, suffix: str) -> int:
        return sum(
            value
            for key, value in details.items()
            if key.endswith(suffix) and isinstance(value, int) and not isinstance(value, bool)
        )

    @staticmethod
    def _contains_safety_flag(value: object) -> bool:
        """Recognize Azure filter flags without retaining the provider payload."""
        if isinstance(value, dict):
            if value.get("filtered") is True:
                return True
            if str(value.get("severity", "")).lower() in {"medium", "high"}:
                return True
            return any(
                AzureOpenAILangChainLLM._contains_safety_flag(item) for item in value.values()
            )
        if isinstance(value, list):
            return any(AzureOpenAILangChainLLM._contains_safety_flag(item) for item in value)
        return False

    @classmethod
    def _safety_outcome(
        cls,
        response_metadata: dict,
        additional_kwargs: dict,
        finish_reason: str,
    ) -> str:
        if finish_reason == "content_filter" or additional_kwargs.get("refusal"):
            return "blocked"
        filter_payloads = [
            source[key]
            for source in (response_metadata, additional_kwargs)
            for key in ("content_filter_results", "prompt_filter_results")
            if key in source
        ]
        if not filter_payloads:
            return "unknown"
        if any(cls._contains_safety_flag(payload) for payload in filter_payloads):
            return "flagged"
        return "clear"

    def _observe_usage(self, call: LLMCall, raw_msg, deployment: str, latency: int, outcome: str):
        if self.usage_observer is None:
            return
        usage = dict(getattr(raw_msg, "usage_metadata", None) or {})
        input_details = dict(usage.get("input_token_details") or {})
        output_details = dict(usage.get("output_token_details") or {})
        response_metadata = dict(getattr(raw_msg, "response_metadata", None) or {})
        additional_kwargs = dict(getattr(raw_msg, "additional_kwargs", None) or {})
        finish_reason = str(
            response_metadata.get("finish_reason") or additional_kwargs.get("finish_reason") or ""
        )[:32]
        metadata = LLMUsage(
            provider=self.key,
            model_deployment=deployment,
            model_name=str(
                response_metadata.get("model_name") or response_metadata.get("model") or deployment
            ),
            provider_request_id=str(
                getattr(raw_msg, "id", "") or response_metadata.get("id") or ""
            ),
            api_version=self.api_version,
            input_tokens=usage.get("input_tokens"),
            cached_input_tokens=self._detail_total(input_details, "cache_read"),
            output_tokens=usage.get("output_tokens"),
            reasoning_tokens=self._detail_total(output_details, "reasoning"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=latency,
            outcome=outcome,
            finish_reason=finish_reason,
            safety_outcome=self._safety_outcome(
                response_metadata,
                additional_kwargs,
                finish_reason,
            ),
        )
        try:
            self.usage_observer(call, metadata)
        except Exception as exc:  # noqa: BLE001 — accounting must not fail document processing
            logger.bind(error_type=type(exc).__name__).warning("llm usage recording failed")

    def _model(self, deployment: str, params: dict):
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_endpoint=self.endpoint,
            api_version=self.api_version,
            azure_deployment=deployment,
            model=deployment,
            **azure_openai_authentication(),
            temperature=params.get("temperature", 0.0),
            max_completion_tokens=params.get("max_tokens", 4000),
            timeout=params.get("timeout_s", 60),
            max_retries=0,
        )  # retries handled by with_retries

    def _observe_failed_usage(
        self, call: LLMCall, exc: Exception, deployment: str, latency: int
    ) -> None:
        """Recover accounting from SDK parse failures without retaining the response content."""
        completion = getattr(exc, "completion", None)
        payload: dict | None
        if completion is not None:
            sdk_usage = getattr(completion, "usage", None)
            choices = getattr(completion, "choices", [])
            payload = {
                "usage": sdk_usage.model_dump() if sdk_usage else None,
                "id": getattr(completion, "id", ""),
                "model": getattr(completion, "model", ""),
                "choices": [
                    {"finish_reason": getattr(choice, "finish_reason", "")} for choice in choices
                ],
            }
        else:
            payload = getattr(exc, "body", None)
        if not isinstance(payload, dict) or not isinstance(payload.get("usage"), dict):
            return  # Do not invent an event or zero tokens for a missing provider response.
        usage = payload["usage"]
        input_details = usage.get("prompt_tokens_details") or {}
        output_details = usage.get("completion_tokens_details") or {}
        choices = payload.get("choices")
        choice = (
            choices[0]
            if isinstance(choices, list) and choices and isinstance(choices[0], dict)
            else {}
        )
        raw_msg = SimpleNamespace(
            id=azure_error_diagnostics(exc).get("provider_request_id") or payload.get("id", ""),
            usage_metadata={
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "input_token_details": {"cache_read": input_details.get("cached_tokens", 0)}
                if isinstance(input_details, dict)
                else {},
                "output_token_details": {"reasoning": output_details.get("reasoning_tokens", 0)}
                if isinstance(output_details, dict)
                else {},
            },
            response_metadata={
                "model_name": payload.get("model", deployment),
                "finish_reason": choice.get("finish_reason", ""),
                **{
                    key: source[key]
                    for source in (payload, choice)
                    for key in ("prompt_filter_results", "content_filter_results")
                    if key in source
                },
            },
            additional_kwargs={},
        )
        self._observe_usage(call, raw_msg, deployment, latency, "invalid_output")

    def invoke(self, call: LLMCall) -> StructuredResult:
        deployment = call.deployment or self.deployment
        params = {**self.parameters, **call.parameters}
        model = self._model(deployment, params)
        structured = model.with_structured_output(call.schema, include_raw=True)
        t0 = time.perf_counter()

        def run():
            try:
                return structured.invoke([("system", call.system), ("user", call.user)])
            except Exception as exc:  # noqa: BLE001 — SDK failures are sanitized by with_retries
                try:
                    self._observe_failed_usage(
                        call, exc, deployment, int((time.perf_counter() - t0) * 1000)
                    )
                except Exception as usage_exc:  # noqa: BLE001 — preserve the original processing failure
                    logger.bind(exception_type=type(usage_exc).__name__).warning(
                        "Failed response usage unavailable"
                    )
                raise

        with logger.contextualize(
            stage=call.stage,
            service=self.key,
            model=deployment,
            chunk_index=call.chunk_index,
            segment_index=call.segment_index,
        ):
            retry_observer = self.retry_observer
            if retry_observer is None:
                out = with_retries(run, max_retries=params.get("max_retries", 2))
            else:
                out = with_retries(
                    run,
                    max_retries=params.get("max_retries", 2),
                    retry_observer=lambda retry_at: retry_observer(call.stage, retry_at),
                )
        latency = int((time.perf_counter() - t0) * 1000)
        raw_msg = out.get("raw")
        raw_text = getattr(raw_msg, "content", "") or json.dumps(
            getattr(raw_msg, "additional_kwargs", {}), default=str
        )
        if out.get("parsing_error") or out.get("parsed") is None:
            self._observe_usage(call, raw_msg, deployment, latency, "invalid_output")
            logger.bind(deployment=deployment, schema=call.schema.__name__).warning(
                "invalid model output"
            )
            raise InvalidModelOutput(
                errors={
                    "schema": call.schema.__name__,
                    "detail": "The model response did not match the extraction response schema.",
                },
                diagnostics=azure_error_diagnostics(out["parsing_error"])
                if isinstance(out.get("parsing_error"), Exception)
                else {"exception_type": "MissingParsedOutput"},
            )
        parsed = out["parsed"]
        try:
            parsed = call.schema.model_validate(
                parsed if isinstance(parsed, dict) else parsed.model_dump()
            )
        except ValidationError as exc:
            self._observe_usage(call, raw_msg, deployment, latency, "invalid_output")
            raise InvalidModelOutput(
                errors={
                    "schema": call.schema.__name__,
                    "detail": "The model response did not match the extraction response schema.",
                },
                diagnostics=azure_error_diagnostics(exc),
            ) from None
        self._observe_usage(call, raw_msg, deployment, latency, "succeeded")
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
