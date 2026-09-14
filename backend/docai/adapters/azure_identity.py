"""Single place credentials are created. Azure identity is the default;
local DI and LLM testing can opt into resource keys through local Django settings.
Token acquisition, endpoint config, timeouts, retries, and error sanitization
all live here so services never touch the SDKs."""

from __future__ import annotations

import functools
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.conf import settings
from loguru import logger
from pydantic import ValidationError

from docai.exceptions import DocAIError, IntegrationError, ThrottledUpstream

if TYPE_CHECKING:
    from azure.core.credentials import AzureKeyCredential
    from azure.identity import DefaultAzureCredential

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"
RetryObserver = Callable[[datetime | None], None]


@functools.lru_cache(maxsize=1)
def credential() -> DefaultAzureCredential:
    """One process-wide credential; the SDK caches and refreshes tokens."""
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


def document_intelligence_credential() -> AzureKeyCredential | DefaultAzureCredential:
    """Only local settings read the optional DI key; other environments use identity."""
    if settings.AZURE_DI_API_KEY:
        from azure.core.credentials import AzureKeyCredential

        return AzureKeyCredential(settings.AZURE_DI_API_KEY)
    return credential()


def token_provider(scope: str = COGNITIVE_SCOPE) -> Callable[[], str]:
    """Bearer-token callable for SDKs that accept one (AzureOpenAI, LangChain)."""

    def _get():
        return credential().get_token(scope).token

    return _get


def azure_openai_authentication() -> dict[str, Any]:
    """Select the local resource key or the refreshable Azure identity token provider."""
    local_key = settings.AZURE_OPENAI_API_KEY
    return {
        "api_key": local_key or None,
        "azure_ad_token_provider": None if local_key else token_provider(),
    }


def azure_settings() -> dict[str, Any]:
    return dict(settings.DOCAI)


def azure_error_diagnostics(exc: Exception) -> dict[str, Any]:
    """Allowlisted SDK metadata only: no exception messages, URLs, headers or bodies."""
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    headers = getattr(response, "headers", {}) or {}
    request_id = (
        getattr(exc, "request_id", None)
        or headers.get("x-request-id")
        or headers.get("apim-request-id")
        or headers.get("x-ms-request-id")
    )
    result: dict[str, Any] = {"exception_type": type(exc).__name__}
    if isinstance(status, int):
        result["upstream_status"] = status
    for key, value in (
        ("provider_request_id", request_id),
        ("provider_error_code", getattr(exc, "code", None)),
    ):
        if isinstance(value, str) and re.fullmatch(r"[\w.:-]{1,128}", value):
            result[key] = value
    cause = exc.__cause__
    if cause is not None:
        result["cause_type"] = type(cause).__name__
    validation = exc if isinstance(exc, ValidationError) else cause
    if isinstance(validation, ValidationError):
        details = validation.errors(include_url=False, include_context=False, include_input=False)
        result["validation_paths"] = ",".join(
            ".".join(map(str, item["loc"])) for item in details[:8]
        )
        result["validation_types"] = ",".join(sorted({item["type"] for item in details[:8]}))
    return result


def sanitize_azure_error(exc: Exception) -> DocAIError:
    if isinstance(exc, DocAIError):
        return exc
    error = _azure_error(exc)
    error.diagnostics = azure_error_diagnostics(exc)
    return error


def _azure_error(exc: Exception) -> IntegrationError:
    """Map SDK exceptions to domain errors without leaking endpoints or payloads."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if name == "LengthFinishReasonError":
        return IntegrationError(
            "The model reached its output limit before completing extraction. Increase the "
            "workflow output limit or process smaller chunks before retrying.",
            error_code="LLM_OUTPUT_TRUNCATED",
            status_code=502,
            retryable=False,
        )
    if name == "ContentFilterFinishReasonError":
        return IntegrationError(
            "The model response was blocked by the provider's content filter.",
            error_code="LLM_CONTENT_FILTERED",
            status_code=502,
            retryable=False,
        )
    if name == "APIResponseValidationError" or (isinstance(status, int) and 200 <= status < 300):
        return IntegrationError(
            "Azure returned a response that could not be read in the expected format. "
            "Reference the trace ID so an operator can check the response diagnostics.",
            error_code="AZURE_RESPONSE_INVALID",
            status_code=502,
            retryable=False,
        )
    if status == 429 or "RateLimit" in name or "Throttl" in name:
        return ThrottledUpstream()
    if status in (401, 403) or "Credential" in name or "Authentication" in name:
        return IntegrationError(
            "Azure authentication failed. Check the configured credentials and resource access.",
            error_code="AZURE_AUTH_FAILED",
            retryable=False,
        )
    if "Timeout" in name or status in (408, 504):
        return IntegrationError("The Azure service timed out.", error_code="AZURE_TIMEOUT")
    if status == 404:
        return IntegrationError(
            "Azure could not find the resource or model deployment. Check the endpoint, "
            "deployment name, and API version before retrying.",
            error_code="AZURE_404",
            retryable=False,
        )
    if status and 400 <= status < 500 and status != 409:
        return IntegrationError(
            "Azure rejected the request. Check the model configuration and input before retrying.",
            error_code=f"AZURE_{status}",
            retryable=False,
        )
    return IntegrationError(
        error_code=f"AZURE_{(status or 'ERROR')}",
        retryable=bool(
            status == 409
            or (status and status >= 500)
            or "Connection" in name
            or name in {"ServiceRequestError", "ServiceResponseError"}
        ),
    )


def with_retries[ResultT](
    fn: Callable[[], ResultT],
    *,
    max_retries: int | None = None,
    base_delay: float = 1.0,
    retry_observer: RetryObserver | None = None,
) -> ResultT:
    """Retry transient Azure failures with exponential backoff. Throttling and
    timeouts retry; configuration, auth, and other permanent failures do not."""
    retries = settings.DOCAI["AZURE_MAX_RETRIES"] if max_retries is None else max_retries
    last: DocAIError | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — sanitized below
            err = sanitize_azure_error(exc)
            last = err
            log = logger.bind(
                **err.diagnostics,
                error_code=err.error_code,
                provider_attempt=attempt + 1,
                retryable=err.retryable,
                reason=err.message,
            )
            if not err.retryable or attempt == retries:
                log.bind(event="provider_call_failed").error("Azure request failed")
                raise err from None
            delay = base_delay * (2**attempt)
            log.bind(event="provider_retry", delay_s=delay).warning("Azure request will retry")
            if retry_observer is not None:
                try:
                    retry_observer(datetime.now(UTC) + timedelta(seconds=delay))
                except Exception as observer_exc:  # noqa: BLE001 -- telemetry is best effort
                    log.bind(error_type=type(observer_exc).__name__).warning(
                        "Provider retry milestone could not be recorded"
                    )
            time.sleep(delay)
            if retry_observer is not None:
                try:
                    retry_observer(None)
                except Exception as observer_exc:  # noqa: BLE001 -- telemetry is best effort
                    log.bind(error_type=type(observer_exc).__name__).warning(
                        "Provider retry resume could not be recorded"
                    )
    if last is None:  # A negative retry count is invalid configuration.
        raise ValueError("max_retries must be zero or greater")
    raise last  # pragma: no cover
