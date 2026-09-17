"""Workflow configuration schemas. A WorkflowConfiguration.config is validated
against the model for its workflow_type before it can be saved or run."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ChunkStrategy = Literal["whole_document", "page", "sheet", "context_length", "semantic"]


class ChunkingConfig(BaseModel):
    strategy: ChunkStrategy = "whole_document"
    chunk_chars: int = Field(default=24000, ge=2000, le=200000)
    overlap_chars: int = Field(default=1500, ge=0, le=20000)
    whole_document_max_chars: int = Field(default=60000, ge=2000)
    fallback: ChunkStrategy | None = Field(
        default="context_length",
        description="Used ONLY when whole_document exceeds max; recorded explicitly",
    )

    max_request_chars: int = Field(
        default=240000,
        ge=2000,
        le=1000000,
        description="Input character guardrail including rendered instructions and output schema; not a token count",
    )

    @model_validator(mode="after")
    def effective_chunking(self):
        if self.fallback == "whole_document":
            raise ValueError("Whole document cannot fall back to itself")
        windowed = self.strategy in ("context_length", "semantic") or (
            self.strategy == "whole_document" and self.fallback in ("context_length", "semantic")
        )
        if windowed and self.overlap_chars >= self.chunk_chars:
            raise ValueError("Overlap must be smaller than the chunk size")
        return self


class LayoutPreservationConfig(BaseModel):
    tables_as_markdown: bool = True
    include_source_ids: bool = True
    link_row_bands: bool = Field(default=True, description="Merge same-row form fields by y-band")
    row_band_tolerance: float = Field(default=0.008, description="Fraction of page height")
    drop_headers_footers: bool = False


class CategoryConfig(BaseModel):
    key: str
    name: str
    description: str = ""
    distinguishing_evidence: str = ""
    aliases: list[str] = Field(default_factory=list)
    continuation_characteristics: str = ""
    extraction_schema: str | None = Field(
        default=None, description="SchemaVersion name to route to"
    )
    extraction_template: str | None = None


class RulePattern(BaseModel):
    pattern: str
    kind: Literal["regex", "phrase", "exact_title", "form_id", "identifier_format"] = "phrase"
    weight: float = 1.0
    group: str | None = None
    case_sensitive: bool = False


class RuleSet(BaseModel):
    category: str
    required: list[RulePattern] = Field(default_factory=list)
    optional: list[RulePattern] = Field(default_factory=list)
    exclusions: list[RulePattern] = Field(default_factory=list)
    threshold: float = Field(default=1.0, ge=0)
    version: str = "1"


class FieldSpec(BaseModel):
    name: str
    description: str = ""
    type: Literal[
        "string",
        "number",
        "integer",
        "date",
        "boolean",
        "currency",
        "percent",
        "identifier",
        "enum",
        "list",
    ] = "string"
    required: bool = False
    enum: list[str] = Field(default_factory=list)
    validation: list[dict] = Field(
        default_factory=list, description="rule dicts, see validation.rules"
    )
    guidance: str = ""
    match_mode: Literal["auto", "exact", "digits", "numeric", "date", "fuzzy"] = "auto"


class ExtractionSchemaConfig(BaseModel):
    name: str
    version: int = 1
    fields: list[FieldSpec]
    mode: Literal["custom", "default"] = "custom"


class ModelSettings(BaseModel):
    adapter: Literal["azure_openai", "mock"] = "azure_openai"
    deployment: str = "gpt-5.2"
    temperature: float = 0.0
    max_tokens: int = 4000
    timeout_s: int = 60
    max_retries: int = 2


class RoutingRule(BaseModel):
    when: dict = Field(
        default_factory=dict,
        description="category/field/criticality/min_score/missing_grounding/validation_failed/disagreement/segmentation_uncertain",
    )
    outcome: Literal["auto_accept", "human_review", "reject"] = "human_review"


class ReconciliationConfig(BaseModel):
    policy: Literal["first_non_null", "highest_score", "majority", "conflicts_to_review"] = (
        "highest_score"
    )


class InputQualityConfig(BaseModel):
    """Snapshotted input preparation policy; native processing remains optional."""

    mode: Literal["off", "adaptive"] = "off"
    skip_blank_pages: bool = False
    profile: Literal["adaptive-v1"] = "adaptive-v1"


class DIAnalysisConfig(BaseModel):
    # Azure add-on; independent of local scan enhancement.
    ocr_high_resolution: bool = False


class BaseWorkflowConfig(BaseModel):
    model: ModelSettings = ModelSettings()
    chunking: ChunkingConfig = ChunkingConfig()
    layout: LayoutPreservationConfig = LayoutPreservationConfig()
    input_quality: InputQualityConfig = Field(default_factory=InputQualityConfig)
    di_analysis: DIAnalysisConfig = Field(default_factory=DIAnalysisConfig)
    routing: list[RoutingRule] = Field(default_factory=list)
    prompt_overrides: dict[str, str] = Field(
        default_factory=dict, description="stage -> prompt name"
    )
    sample_size: int | None = None


class SegmentationConfig(BaseModel):
    """Character-budget guardrails, including the response schema and output reserve.

    Four characters per reserved output token is a planning approximation, not a
    tokenizer or a guarantee about any particular model's context window.
    """

    model_config = {"extra": "forbid"}
    window_pages: int = Field(default=12, ge=2, le=100)
    overlap_pages: int = Field(default=2, ge=1, le=20)
    page_chars: int = Field(default=3000, ge=500, le=20000)
    request_budget_chars: int = Field(default=60000, ge=12000, le=400000)
    output_tokens: int = Field(default=4000, ge=500, le=16000)

    @model_validator(mode="after")
    def _budget(self):
        if self.overlap_pages >= self.window_pages:
            raise ValueError("segmentation overlap_pages must be smaller than window_pages")
        if self.output_tokens * 4 >= self.request_budget_chars:
            raise ValueError("segmentation request budget must leave room for input")
        return self


class UnbundleClassifyExtractConfig(BaseWorkflowConfig):
    categories: list[CategoryConfig] = Field(min_length=1)
    schemas: list[ExtractionSchemaConfig] = Field(default_factory=list)
    other_behavior: Literal["keep_other", "needs_review"] = "needs_review"
    segmentation: SegmentationConfig = Field(default_factory=SegmentationConfig)

    @model_validator(mode="before")
    @classmethod
    def _retired_strategy(cls, value):
        if isinstance(value, dict) and "segmentation_strategy" in value:
            raise ValueError("segmentation_strategy is retired; use the segmentation settings")
        return value

    reconciliation: ReconciliationConfig = ReconciliationConfig()

    @model_validator(mode="after")
    def _routes_exist(self):
        names = {s.name for s in self.schemas}
        for c in self.categories:
            if c.extraction_schema and c.extraction_schema not in names:
                raise ValueError(f"category {c.key} routes to unknown schema {c.extraction_schema}")
        return self


class ClassifyStructuredConfig(BaseWorkflowConfig):
    rules: list[RuleSet] = Field(min_length=1)
    use_llm_fallback: bool = False
    categories: list[CategoryConfig] = Field(default_factory=list)
    ambiguity_margin: float = Field(default=0.5, ge=0)


class ClassifyUnstructuredConfig(BaseWorkflowConfig):
    categories: list[CategoryConfig] = Field(min_length=1)
    segment_first: bool = False


class ExtractStructuredConfig(BaseWorkflowConfig):
    mode: Literal["default", "custom"] = "custom"
    schema_: ExtractionSchemaConfig | None = Field(default=None, alias="schema")
    document_type: str | None = None
    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _custom_needs_schema(self):
        if self.mode == "custom" and self.schema_ is None:
            raise ValueError("custom mode requires a schema")
        return self


class ExtractUnstructuredConfig(BaseWorkflowConfig):
    schema_: ExtractionSchemaConfig = Field(alias="schema")
    document_type: str | None = None
    reconciliation: ReconciliationConfig = ReconciliationConfig()
    model_config = {"populate_by_name": True}


class ExtractTemplateConfig(BaseWorkflowConfig):
    template_name: str
    template_version: int


class EvaluateConfig(BaseModel):
    normalization: dict = Field(default_factory=dict)
    numeric_tolerance: float = 0.01


CONFIG_SCHEMAS: dict[str, type[BaseModel]] = {
    "unbundle_classify_extract": UnbundleClassifyExtractConfig,
    "classify_structured": ClassifyStructuredConfig,
    "classify_unstructured": ClassifyUnstructuredConfig,
    "extract_structured": ExtractStructuredConfig,
    "extract_unstructured": ExtractUnstructuredConfig,
    "extract_template": ExtractTemplateConfig,
    "evaluate": EvaluateConfig,
}


def validate_workflow_config(workflow_type: str, config: dict[str, Any]) -> dict[str, Any]:
    model = CONFIG_SCHEMAS.get(workflow_type)
    if model is None:
        raise ValueError(f"unknown workflow type {workflow_type}")
    return model.model_validate(config).model_dump(by_alias=True)
