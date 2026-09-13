"""Single place credentials are created. Azure identity is the default;
local DI and LLM testing can opt into resource keys through local Django settings.
Token acquisition, endpoint config, timeouts, retries, and error sanitization
all live here so services never touch the SDKs."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from django.conf import settings
from loguru import logger

from docai.exceptions import IntegrationError, ThrottledUpstream

if TYPE_CHECKING:
    from azure.core.credentials import AzureKeyCredential
    from azure.identity import DefaultAzureCredential

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


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


def sanitize_azure_error(exc: Exception) -> DocAIErrorLike:
    """Map SDK exceptions to domain errors without leaking endpoints or payloads."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
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


DocAIErrorLike = IntegrationError


def with_retries[ResultT](
    fn: Callable[[], ResultT], *, max_retries: int | None = None, base_delay: float = 1.0
) -> ResultT:
    """Retry transient Azure failures with exponential backoff. Throttling and
    timeouts retry; configuration, auth, and other permanent failures do not."""
    retries = settings.DOCAI["AZURE_MAX_RETRIES"] if max_retries is None else max_retries
    last: DocAIErrorLike | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — sanitized below
            err = sanitize_azure_error(exc)
            last = err
            if not err.retryable or attempt == retries:
                logger.bind(error_code=err.error_code, attempt=attempt + 1).warning(
                    "azure call failed"
                )
                raise err from None
            delay = base_delay * (2**attempt)
            logger.bind(error_code=err.error_code, attempt=attempt + 1, delay_s=delay).info(
                "azure retry"
            )
            time.sleep(delay)
    if last is None:  # A negative retry count is invalid configuration.
        raise ValueError("max_retries must be zero or greater")
    raise last  # pragma: no cover
