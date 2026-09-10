"""§5.6 Template extraction: the run's context is built from the template
(schema, prompt, model, guidance, chunking) by the run service; here we
execute through the same core and stamp the template identity."""
from __future__ import annotations

from docai.schemas.config import ExtractionSchemaConfig
from docai.schemas.layout import LayoutDocument

from .base import DocumentResult, WorkflowContext, register
from .extraction_core import run_extraction


@register
class ExtractTemplate:
    key = "extract_template"

    def process_document(self, ctx: WorkflowContext, layout: LayoutDocument) -> DocumentResult:
        cfg = ctx.config
        tpl = getattr(ctx, "template", None) or {}
        schema = ExtractionSchemaConfig.model_validate(tpl["schema"])
        res = run_extraction(ctx, layout, schema, document_type=tpl.get("document_type"),
                             guidance=tpl.get("field_guidance") or {})
        for f in res.fields:
            f.method = "template"
            f.fallback_used = (f.fallback_used + "; " if f.fallback_used else "") + \
                f"template={cfg.template_name} v{cfg.template_version}"
        return res
