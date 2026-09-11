"""Projects, datasets, and the governed configuration catalog: category
definitions, prompt/schema versions, extraction templates, workflow and model
configurations, review policies. Versioned objects are immutable: a change is
a new version row, never an update in place."""

from __future__ import annotations

from django.db import models
from model_utils import Choices, FieldTracker

from .base import AuditedModel, SoftDeletableAuditedModel, ix

WORKFLOW_TYPES = Choices(
    ("unbundle_classify_extract", "Unbundling + classification + extraction"),
    ("classify_structured", "Classification only: structured (rules + optional LLM)"),
    ("classify_unstructured", "Classification only: unstructured (LLM)"),
    ("extract_structured", "Extraction only: structured (layout-preserved, generic extractor)"),
    ("extract_unstructured", "Extraction only: unstructured (LLM strategies)"),
    ("extract_template", "Extraction only: versioned template"),
    ("evaluate", "Evaluation of predictions against ground truth"),
)
CONFIG_STATUS = Choices(("draft", "Draft"), ("approved", "Approved"), ("retired", "Retired"))
DATASET_SPLIT = Choices(
    ("train", "Training"),
    ("dev", "Development"),
    ("validation", "Validation"),
    ("test", "Test"),
    ("unsplit", "Unsplit"),
)


class Project(SoftDeletableAuditedModel):
    name = models.CharField(
        max_length=120,
        db_comment="Project display name",
        help_text="Business-facing name, e.g. 'Commercial loan onboarding'.",
    )
    slug = models.SlugField(
        max_length=64,
        unique=True,
        db_comment="URL-safe unique key",
        help_text="Unique short key used in URLs and exports.",
    )
    description = models.TextField(
        blank=True,
        db_comment="Purpose of the project",
        help_text="What this project processes and for whom.",
    )

    class Meta:
        db_table = "docai_project"
        db_table_comment = "A business use case grouping datasets, configurations and runs"
        verbose_name = "project"
        verbose_name_plural = "projects"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"], name=ix("ix_docai_proj_name")),
            models.Index(fields=["created"], name=ix("ix_docai_proj_created")),
        ]

    def __str__(self):
        return self.name


class Dataset(SoftDeletableAuditedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="datasets",
        db_comment="Owning project",
        help_text="Project this dataset belongs to.",
    )
    name = models.CharField(max_length=120, db_comment="Dataset name", help_text="Dataset name.")
    split = models.CharField(
        max_length=12,
        choices=DATASET_SPLIT,
        default=DATASET_SPLIT.unsplit,
        db_comment="train/dev/validation/test role to prevent leakage",
        help_text="Role in experiments. Test data must never inform prompt changes.",
    )
    description = models.TextField(blank=True, db_comment="Notes", help_text="Notes on provenance.")
    is_production = models.BooleanField(
        default=False,
        db_comment="Production data flag",
        help_text="Controlled experiments may only run on non-production datasets.",
    )

    class Meta:
        db_table = "docai_dataset"
        db_table_comment = "A named collection of documents within a project, with a split role"
        verbose_name = "dataset"
        verbose_name_plural = "datasets"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name=ix("uq_docai_ds_proj_name"))
        ]
        indexes = [
            models.Index(fields=["project", "split"], name=ix("ix_docai_ds_proj_split")),
            models.Index(fields=["created"], name=ix("ix_docai_ds_created")),
        ]

    def __str__(self):
        return f"{self.project.slug}/{self.name}"


class CategoryDefinition(AuditedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="categories",
        db_comment="Owning project",
        help_text="Project scope.",
    )
    key = models.SlugField(
        max_length=64,
        db_comment="Stable category id",
        help_text="Stable id used by workflows, e.g. 'w2'.",
    )
    name = models.CharField(max_length=120, db_comment="Display name", help_text="Human name.")
    description = models.TextField(
        db_comment="Semantic description for the LLM",
        help_text="What the document is; used verbatim in prompts.",
    )
    distinguishing_evidence = models.TextField(
        blank=True,
        db_comment="Cues that identify this type",
        help_text="Headings, form ids, phrases that identify it.",
    )
    aliases = models.JSONField(
        default=list,
        blank=True,
        db_comment="Alternate names (list)",
        help_text="Alternate names the type may go by.",
    )
    continuation_characteristics = models.TextField(
        blank=True,
        db_comment="What continuation pages look like",
        help_text="How page 2+ of this document looks (helps segmentation).",
    )
    version = models.PositiveIntegerField(
        default=1, db_comment="Definition version", help_text="Immutable version."
    )

    class Meta:
        db_table = "docai_category_definition"
        db_table_comment = (
            "Versioned document category definitions used by classification and unbundling"
        )
        verbose_name = "category definition"
        verbose_name_plural = "category definitions"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "key", "version"], name=ix("uq_docai_cat_key_ver")
            )
        ]
        indexes = [models.Index(fields=["project", "key"], name=ix("ix_docai_cat_proj_key"))]

    def __str__(self):
        return f"{self.key} v{self.version}"


class SchemaVersion(AuditedModel):
    name = models.CharField(
        max_length=120, db_comment="Schema name", help_text="Pydantic schema name."
    )
    version = models.PositiveIntegerField(
        db_comment="Schema version", help_text="Immutable version number."
    )
    json_schema = models.JSONField(
        db_comment="Exported JSON schema", help_text="Pydantic model_json_schema() export."
    )
    field_definitions = models.JSONField(
        default=list,
        db_comment="Field list (name, type, required, enum, rules)",
        help_text="Editable field definitions the schema was built from.",
    )

    class Meta:
        db_table = "docai_schema_version"
        db_table_comment = "Immutable versions of extraction/classification output schemas"
        verbose_name = "schema version"
        verbose_name_plural = "schema versions"
        constraints = [
            models.UniqueConstraint(fields=["name", "version"], name=ix("uq_docai_schema_name_ver"))
        ]
        indexes = [models.Index(fields=["name"], name=ix("ix_docai_schema_name"))]

    def __str__(self):
        return f"{self.name} v{self.version}"


class PromptVersion(AuditedModel):
    name = models.CharField(
        max_length=120, db_comment="Prompt name", help_text="Prompt family name."
    )
    version = models.PositiveIntegerField(
        db_comment="Prompt version", help_text="Immutable version number."
    )
    purpose = models.CharField(
        max_length=32,
        db_comment="segmentation|classification|extraction",
        help_text="Which stage this prompt serves.",
    )
    system_prompt = models.TextField(db_comment="System prompt text", help_text="System prompt.")
    user_template = models.TextField(
        db_comment="User prompt template with {placeholders}",
        help_text="Template; content is injected at run time.",
    )
    content_hash = models.CharField(
        max_length=71,
        db_comment="sha256 of the prompt content",
        help_text="Integrity hash of system + template.",
    )

    class Meta:
        db_table = "docai_prompt_version"
        db_table_comment = "Immutable prompt versions; every run records which it used"
        verbose_name = "prompt version"
        verbose_name_plural = "prompt versions"
        constraints = [
            models.UniqueConstraint(fields=["name", "version"], name=ix("uq_docai_prompt_name_ver"))
        ]
        indexes = [models.Index(fields=["purpose"], name=ix("ix_docai_prompt_purpose"))]

    def __str__(self):
        return f"{self.name} v{self.version}"


class ModelConfiguration(AuditedModel):
    name = models.CharField(max_length=120, db_comment="Config name", help_text="Display name.")
    version = models.PositiveIntegerField(
        default=1, db_comment="Version", help_text="Immutable version."
    )
    adapter = models.CharField(
        max_length=32,
        db_comment="LLM adapter key (azure_openai|mock)",
        help_text="Which adapter executes calls. Swapping models never changes workflow logic.",
    )
    deployment = models.CharField(
        max_length=120, db_comment="Azure deployment name", help_text="Azure OpenAI deployment."
    )
    parameters = models.JSONField(
        default=dict,
        blank=True,
        db_comment="temperature, max_tokens, etc.",
        help_text="Model parameters.",
    )

    class Meta:
        db_table = "docai_model_configuration"
        db_table_comment = "Versioned model deployment + parameter settings"
        verbose_name = "model configuration"
        verbose_name_plural = "model configurations"
        constraints = [
            models.UniqueConstraint(fields=["name", "version"], name=ix("uq_docai_model_name_ver"))
        ]

    def __str__(self):
        return f"{self.name} v{self.version} ({self.deployment})"


class ExtractionTemplate(AuditedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="templates",
        db_comment="Owning project",
        help_text="Project scope.",
    )
    name = models.CharField(max_length=120, db_comment="Template name", help_text="Template name.")
    version = models.PositiveIntegerField(
        default=1, db_comment="Version", help_text="Immutable version."
    )
    document_type = models.CharField(
        max_length=64, db_comment="Target category key", help_text="Document type it extracts."
    )
    schema_version = models.ForeignKey(
        SchemaVersion,
        on_delete=models.PROTECT,
        related_name="templates",
        db_comment="Output schema",
        help_text="Pydantic output schema version.",
    )
    prompt_version = models.ForeignKey(
        PromptVersion,
        on_delete=models.PROTECT,
        related_name="templates",
        db_comment="Prompt used",
        help_text="Prompt version.",
    )
    model_config = models.ForeignKey(
        ModelConfiguration,
        on_delete=models.PROTECT,
        related_name="templates",
        db_comment="Model settings",
        help_text="Model configuration.",
    )
    field_guidance = models.JSONField(
        default=dict,
        blank=True,
        db_comment="Per-field guidance text",
        help_text="Where each field lives, formats, confusers.",
    )
    validations = models.JSONField(
        default=list,
        blank=True,
        db_comment="Validation rules",
        help_text="Regex/range/cross-field rules applied post-extraction.",
    )
    source_expectations = models.JSONField(
        default=dict,
        blank=True,
        db_comment="Expected pages/regions",
        help_text="Where fields are expected (page, region).",
    )
    chunking = models.JSONField(
        default=dict,
        blank=True,
        db_comment="Chunking strategy config",
        help_text="Strategy, chunk size, overlap.",
    )
    status = models.CharField(
        max_length=12,
        choices=CONFIG_STATUS,
        default=CONFIG_STATUS.draft,
        db_comment="draft|approved|retired",
        help_text="Governance status.",
    )

    class Meta:
        db_table = "docai_extraction_template"
        db_table_comment = "Reusable versioned extraction templates (schema+prompt+model+guidance)"
        verbose_name = "extraction template"
        verbose_name_plural = "extraction templates"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "name", "version"], name=ix("uq_docai_tpl_name_ver")
            )
        ]
        indexes = [
            models.Index(fields=["project", "document_type"], name=ix("ix_docai_tpl_proj_type")),
            models.Index(fields=["status"], name=ix("ix_docai_tpl_status")),
        ]

    def __str__(self):
        return f"{self.name} v{self.version}"


class WorkflowConfiguration(AuditedModel):
    """The immutable, hashed unit a run snapshots. `config` holds everything
    workflow-specific (categories, rules, schemas, chunking, layout
    preservation, validation, routing, model settings, prompt refs)."""

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="workflows",
        db_comment="Owning project",
        help_text="Project scope.",
    )
    name = models.CharField(max_length=120, db_comment="Workflow name", help_text="Workflow name.")
    version = models.PositiveIntegerField(
        default=1, db_comment="Version", help_text="Immutable version."
    )
    workflow_type = models.CharField(
        max_length=32,
        choices=WORKFLOW_TYPES,
        db_comment="Strategy key",
        help_text="Which workflow strategy executes this configuration.",
    )
    config = models.JSONField(
        default=dict,
        db_comment="Full workflow configuration",
        help_text="Validated against the workflow's Pydantic config schema.",
    )
    content_hash = models.CharField(
        max_length=71,
        blank=True,
        db_comment="sha256 of config",
        help_text="Integrity hash; runs record it.",
    )
    status = models.CharField(
        max_length=12,
        choices=CONFIG_STATUS,
        default=CONFIG_STATUS.draft,
        db_comment="draft|approved|retired",
        help_text="Governance status.",
    )
    approved_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        db_comment="Approver",
        help_text="Who approved promotion.",
    )
    approved_at = models.DateTimeField(
        null=True, blank=True, db_comment="Approval time", help_text="When approved."
    )
    tracker = FieldTracker(fields=["status", "config"])

    class Meta:
        db_table = "docai_workflow_configuration"
        db_table_comment = (
            "Versioned workflow configurations; approval required before production use"
        )
        verbose_name = "workflow configuration"
        verbose_name_plural = "workflow configurations"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "name", "version"], name=ix("uq_docai_wf_name_ver")
            )
        ]
        indexes = [
            models.Index(fields=["project", "workflow_type"], name=ix("ix_docai_wf_proj_type")),
            models.Index(fields=["status"], name=ix("ix_docai_wf_status")),
            models.Index(fields=["content_hash"], name=ix("ix_docai_wf_hash")),
        ]

    def __str__(self):
        return f"{self.name} v{self.version} [{self.workflow_type}]"


class ReviewPolicy(AuditedModel):
    workflow = models.ForeignKey(
        WorkflowConfiguration,
        on_delete=models.CASCADE,
        related_name="review_policies",
        db_comment="Workflow",
        help_text="Workflow this policy applies to.",
    )
    name = models.CharField(max_length=120, db_comment="Policy name", help_text="Policy name.")
    rules = models.JSONField(
        default=list,
        db_comment="Routing rules (JSON)",
        help_text="Ordered rules: match on category/field/criticality/threshold/"
        "missing grounding/validation failure/disagreement/segmentation "
        "uncertainty → auto_accept | human_review | reject.",
    )
    is_active = models.BooleanField(
        default=True, db_comment="Active flag", help_text="Active flag."
    )

    class Meta:
        db_table = "docai_review_policy"
        db_table_comment = "Rules deciding auto-accept, human review, or reject per prediction"
        verbose_name = "review policy"
        verbose_name_plural = "review policies"
        indexes = [models.Index(fields=["workflow", "is_active"], name=ix("ix_docai_rp_wf_active"))]
