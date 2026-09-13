"""Exercise real SDK exception contracts offline, without sending document content."""

from types import SimpleNamespace

import httpx2
import pytest
from loguru import logger
from openai import (
    APIResponseValidationError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
)
from openai.types.chat import ChatCompletion

from docai.adapters.azure_identity import sanitize_azure_error
from docai.adapters.llm.azure_openai import AzureOpenAILangChainLLM
from docai.adapters.llm.base import LLMCall
from docai.exceptions import IntegrationError
from docai.schemas.llm import ClassificationOut


def completion_payload(finish_reason="length"):
    return {
        "id": "chatcmpl-test",
        "created": 1,
        "model": "test-deployment",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": "private-document-content"},
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 4000,
            "total_tokens": 4120,
            "prompt_tokens_details": {"cached_tokens": 20},
            "completion_tokens_details": {"reasoning_tokens": 800},
        },
    }


@pytest.mark.parametrize("kind", ["invalid_response", "length", "content_filter", "no_usage"])
def test_failed_sdk_response_preserves_diagnostics_and_available_usage(monkeypatch, settings, kind):
    settings.DOCAI = {**settings.DOCAI, "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com"}
    observed, records, calls = [], [], []
    payload = completion_payload()
    response = httpx2.Response(
        200,
        request=httpx2.Request("POST", "https://example.invalid"),
        headers={"x-request-id": "provider-request-123", "authorization": "private-auth"},
    )
    error: Exception
    if kind in {"invalid_response", "no_usage"}:
        error = APIResponseValidationError(
            response,
            payload if kind == "invalid_response" else {},
            message="private-sdk-error-message",
        )
        code = "AZURE_RESPONSE_INVALID"
    elif kind == "length":
        error = LengthFinishReasonError(completion=ChatCompletion.model_validate(payload))
        code = "LLM_OUTPUT_TRUNCATED"
    else:
        error = ContentFilterFinishReasonError()
        code = "LLM_CONTENT_FILTERED"

    def invoke(messages):
        calls.append(messages)
        raise error

    adapter = AzureOpenAILangChainLLM(usage_observer=lambda call, usage: observed.append(usage))
    monkeypatch.setattr(
        adapter,
        "_model",
        lambda *args: SimpleNamespace(
            with_structured_output=lambda *args, **kwargs: SimpleNamespace(invoke=invoke)
        ),
    )
    sink = logger.add(lambda message: records.append(message.record))
    try:
        with (
            logger.contextualize(attempt=3, run_id="run-1", item_id="item-1"),
            pytest.raises(IntegrationError) as raised,
        ):
            adapter.invoke(
                LLMCall(
                    system="private-prompt",
                    user="private-document-content",
                    schema=ClassificationOut,
                    stage="extraction",
                    chunk_index=0,
                )
            )
    finally:
        logger.remove(sink)
    assert raised.value.error_code == code
    assert not raised.value.retryable
    assert len(calls) == 1  # Retrying the same response/configuration does not fix it.
    failure = next(r for r in records if r["extra"].get("event") == "provider_call_failed")
    assert failure["level"].name == "ERROR"
    assert failure["extra"]["exception_type"] == type(error).__name__
    assert failure["extra"]["attempt"] == 3
    assert failure["extra"]["provider_attempt"] == 1
    assert failure["extra"]["stage"] == "extraction"
    assert failure["extra"]["service"] == "azure_openai"
    assert failure["extra"]["chunk_index"] == 0
    assert "private-" not in str([(r["message"], r["extra"]) for r in records])
    assert "private-" not in str(raised.value.errors)
    if kind in {"invalid_response", "no_usage"}:
        assert failure["extra"]["upstream_status"] == 200
        assert failure["extra"]["provider_request_id"] == "provider-request-123"
    if kind in {"length", "invalid_response"}:
        assert len(observed) == 1
        assert observed[0].outcome == "invalid_output"
        assert observed[0].input_tokens == 120
        assert observed[0].output_tokens == 4000
        assert observed[0].total_tokens == 4120
        assert observed[0].reasoning_tokens == 800
        assert observed[0].cached_input_tokens == 20
        assert observed[0].finish_reason == "length"
    else:
        assert observed == []


def test_any_success_http_status_on_an_exception_is_a_response_failure():
    error = type("UnexpectedSDKError", (Exception,), {"status_code": 200})("private-response")
    mapped = sanitize_azure_error(error)
    assert mapped.error_code == "AZURE_RESPONSE_INVALID"
    assert mapped.diagnostics["exception_type"] == "UnexpectedSDKError"
    assert "private-response" not in str(mapped)


def test_existing_domain_errors_are_not_relabelled_as_azure_errors():
    error = IntegrationError("Known failure", error_code="CUSTOM_FAILURE", retryable=False)
    assert sanitize_azure_error(error) is error


def test_response_validation_diagnostics_keep_field_paths_without_inputs():
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as caught:
        ClassificationOut.model_validate({"category": {"private-input": "private-value"}})
    response = httpx2.Response(200, request=httpx2.Request("POST", "https://example.invalid"))
    error = APIResponseValidationError(response, {"private-payload": "private-value"})
    error.__cause__ = caught.value
    mapped = sanitize_azure_error(error)
    assert mapped.diagnostics["cause_type"] == "ValidationError"
    assert mapped.diagnostics["validation_paths"] == "category"
    assert mapped.diagnostics["validation_types"] == "string_type"
    assert "private-" not in str(mapped.diagnostics)
