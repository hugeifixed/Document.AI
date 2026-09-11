"""LayoutProvider protocol + registry. Services ask for `get_layout_provider()`
and never import a vendor SDK."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from django.conf import settings

from docai.schemas.layout import LayoutDocument


class LayoutProvider(Protocol):
    key: str
    supports_ocr: bool

    def analyze(self, path: Path, *, document_id: str, source_format: str) -> LayoutDocument: ...


def get_layout_provider(key: str | None = None) -> LayoutProvider:
    key = key or str(settings.DOCAI["LAYOUT_ADAPTER"])
    if key == "azure_di":
        from .azure_di import AzureDocumentIntelligenceLayout

        return AzureDocumentIntelligenceLayout()
    if key == "pypdf":
        from .pypdf_text import PypdfTextLayerLayout

        return PypdfTextLayerLayout()
    if key == "fixture":
        from .fixture import FixtureLayout

        return FixtureLayout()
    raise ValueError(f"unknown layout adapter {key}")
