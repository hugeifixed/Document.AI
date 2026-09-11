"""§5.5 Unstructured extraction: configurable strategy (whole/page/semantic/
context-length) → reconciliation → validation, via the shared core; strategy
and any fallback are recorded on every field."""

from __future__ import annotations

from docai.schemas.layout import LayoutDocument

from .base import DocumentResult, WorkflowContext, register
from .extraction_core import run_extraction


@register
class ExtractUnstructured:
    key = "extract_unstructured"

    def process_document(self, ctx: WorkflowContext, layout: LayoutDocument) -> DocumentResult:
        cfg = ctx.config
        return run_extraction(
            ctx,
            layout,
            cfg.schema_,
            document_type=cfg.document_type,
            reconciliation_policy=cfg.reconciliation.policy,
        )
