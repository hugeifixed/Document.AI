"""Single place credentials are created. `az login` locally, managed identity
when deployed — DefaultAzureCredential resolves both. No API keys anywhere.
Token acquisition, endpoint config, timeouts, retries, and error sanitization
all live here so services never touch the SDKs."""
from __future__ import annotations

import functools
import time
from collections.abc import Callable

from django.conf import settings
from loguru import logger

from docai.exceptions import IntegrationError, ThrottledUpstream

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


@functools.lru_cache(maxsize=1)
def credential():
    """One process-wide credential; the SDK caches and refreshes tokens."""
    from azure.identity import DefaultAzureCredential
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


def token_provider(scope: str = COGNITIVE_SCOPE) -> Callable[[], str]:
    """Bearer-token callable for SDKs that accept one (AzureOpenAI, LangChain)."""
    def _get():
        return credential().get_token(scope).token
    return _get


def azure_settings() -> dict:
    return settings.DOCAI


def sanitize_azure_error(exc: Exception) -> DocAIErrorLike:
    """Map SDK exceptions to domain errors without leaking endpoints or payloads."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if status == 429 or "RateLimit" in name or "Throttl" in name:
        return ThrottledUpstream()
    if status in (401, 403) or "Credential" in name or "Authentication" in name:
        return IntegrationError("Azure authentication failed. Run `az login` locally or check the managed identity.",
                                error_code="AZURE_AUTH_FAILED", retryable=False)
    if "Timeout" in name or status in (408, 504):
        return IntegrationError("The Azure service timed out.", error_code="AZURE_TIMEOUT")
    return IntegrationError(error_code=f"AZURE_{(status or 'ERROR')}")


DocAIErrorLike = IntegrationError


def with_retries(fn: Callable, *, max_retries: int | None = None, base_delay: float = 1.0):
    """Retry transient Azure failures with exponential backoff. Throttling and
    timeouts retry; auth failures do not."""
    retries = settings.DOCAI["AZURE_MAX_RETRIES"] if max_retries is None else max_retries
    last = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — sanitized below
            err = sanitize_azure_error(exc)
            last = err
            if not err.retryable or attempt == retries:
                logger.bind(error_code=err.error_code, attempt=attempt + 1).warning("azure call failed")
                raise err from None
            delay = base_delay * (2 ** attempt)
            logger.bind(error_code=err.error_code, attempt=attempt + 1, delay_s=delay).info("azure retry")
            time.sleep(delay)
    raise last  # pragma: no cover
