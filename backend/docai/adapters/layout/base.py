"""LayoutProvider protocol + registry. Services ask for `get_layout_provider()`
and never import a vendor SDK."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from django.conf import settings

from docai.schemas.layout import LayoutDocument


class LayoutProvider(Protocol):
    key: str
    supports_ocr: bool

    def analyze(
        self,
        path: Path,
        *,
        document_id: str,
        source_format: str,
        pages: str | None = None,
        ocr_high_resolution: bool = False,
    ) -> LayoutDocument: ...


def get_layout_provider(
    key: str | None = None, *, retry_observer: Callable[[datetime | None], None] | None = None
) -> LayoutProvider:
    key = key or str(settings.DOCAI["LAYOUT_ADAPTER"])
    if key == "azure_di":
        from .azure_di import AzureDocumentIntelligenceLayout

        return AzureDocumentIntelligenceLayout(retry_observer=retry_observer)
    if key == "pypdf":
        from .pypdf_text import PypdfTextLayerLayout

        return PypdfTextLayerLayout()
    if key == "fixture":
        from .fixture import FixtureLayout

        return FixtureLayout()
    if key == "excel":
        from .excel import ExcelLayout

        return ExcelLayout()
    if key == "plain_text":
        from .plain_text import PlainTextLayout

        return PlainTextLayout()
    raise ValueError(f"unknown layout adapter {key}")


def get_layout_provider_for_format(
    source_format: str,
    configured_key: str | None = None,
    *,
    retry_observer: Callable[[datetime | None], None] | None = None,
) -> LayoutProvider:
    """Resolve every supported source format behind the layout provider seam."""
    if source_format in {"xlsx", "xls"}:
        return get_layout_provider("excel")
    if source_format == "txt":
        return get_layout_provider("plain_text")
    return get_layout_provider(configured_key, retry_observer=retry_observer)
