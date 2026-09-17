"""Documents, their immutable processing artifacts, and source units
(pages or worksheets). Originals are never modified; every transformation is
a new artifact with its parameters and a page map so spans stay traceable."""

from __future__ import annotations

from django.db import models
from model_utils import Choices, FieldTracker
from model_utils.models import StatusModel

from .base import AuditedModel, ix
from .catalog import Dataset

DOC_STATUS = Choices(
    ("uploaded", "Uploaded"),
    ("validated", "Validated"),
    ("rejected", "Rejected"),
    ("processing", "Processing"),
    ("processed", "Processed"),
    ("failed", "Failed"),
)
SOURCE_KIND = Choices(("page", "Page"), ("sheet", "Worksheet"))
ARTIFACT_KIND = Choices(
    ("original", "Original file"),
    ("normalized_image", "Normalized page image"),
    ("layout", "Normalized layout (OCR/Layout or Excel)"),
    ("preserved_text", "Layout-preserved text"),
    ("raw_service", "Raw service response"),
    ("raw_model_response", "Raw model response"),
)
SUPPORTED_MIME = {
    "application/pdf": "pdf",
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/tiff": "tiff",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "text/plain": "txt",
}


class Document(StatusModel, AuditedModel):
    STATUS = DOC_STATUS
    RUNNABLE_STATUSES = (DOC_STATUS.validated, DOC_STATUS.processed, DOC_STATUS.failed)
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.PROTECT,
        related_name="documents",
        db_comment="Owning dataset",
        help_text="Dataset this document belongs to.",
    )
    original_filename = models.CharField(
        max_length=255,
        db_comment="Filename as uploaded",
        help_text="Original filename (display only; storage names are safe).",
    )
    source = models.CharField(
        max_length=64,
        default="upload",
        db_comment="upload|folder|api",
        help_text="How the document arrived.",
    )
    mime_type = models.CharField(
        max_length=120, db_comment="Detected MIME type", help_text="Detected MIME type."
    )
    file_format = models.CharField(
        max_length=8,
        db_comment="pdf|jpeg|png|tiff|docx|xlsx|xls|txt",
        help_text="Normalized format key.",
    )
    sha256 = models.CharField(
        max_length=64,
        db_comment="Content hash (duplicate detection)",
        help_text="SHA-256 of the original bytes.",
    )
    size_bytes = models.BigIntegerField(db_comment="Size in bytes", help_text="Original size.")
    page_count = models.PositiveIntegerField(
        default=0, db_comment="Pages (0 for spreadsheets)", help_text="Page count."
    )
    sheet_count = models.PositiveIntegerField(
        default=0, db_comment="Worksheets (spreadsheets)", help_text="Sheet count."
    )
    storage_path = models.CharField(
        max_length=255,
        db_comment="Path of the original in storage",
        help_text="Windows-safe relative storage path of the original.",
    )
    validation_errors = models.JSONField(
        default=list,
        blank=True,
        db_comment="Rejection reasons",
        help_text="Why validation rejected this file, if it did.",
    )
    metadata = models.JSONField(
        default=dict, blank=True, db_comment="Misc metadata", help_text="Extra metadata."
    )
    tracker = FieldTracker(fields=["status"])

    class Meta:
        db_table = "docai_document"
        db_table_comment = "An uploaded source file; originals are immutable"
        verbose_name = "document"
        verbose_name_plural = "documents"
        ordering = ["-created"]
        constraints = [
            models.UniqueConstraint(fields=["dataset", "sha256"], name=ix("uq_docai_doc_ds_hash"))
        ]
        indexes = [
            models.Index(fields=["dataset", "status"], name=ix("ix_docai_doc_ds_status")),
            models.Index(fields=["sha256"], name=ix("ix_docai_doc_hash")),
            models.Index(fields=["original_filename"], name=ix("ix_docai_doc_filename")),
            models.Index(fields=["file_format"], name=ix("ix_docai_doc_format")),
            models.Index(fields=["created"], name=ix("ix_docai_doc_created")),
            models.Index(fields=["modified"], name=ix("ix_docai_doc_modified")),
        ]

    def __str__(self):
        return self.original_filename


class ProcessingArtifact(AuditedModel):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="artifacts",
        db_comment="Owning document",
        help_text="Document this artifact derives from.",
    )
    kind = models.CharField(
        max_length=24, choices=ARTIFACT_KIND, db_comment="Artifact kind", help_text="Artifact kind."
    )
    stage = models.CharField(
        max_length=64, blank=True, db_comment="Producing stage", help_text="Pipeline stage."
    )
    storage_path = models.CharField(
        max_length=255, db_comment="Path in storage", help_text="Relative storage path."
    )
    sha256 = models.CharField(
        max_length=64, db_comment="Content hash", help_text="SHA-256 of the artifact."
    )
    size_bytes = models.BigIntegerField(default=0, db_comment="Size", help_text="Size in bytes.")
    parameters = models.JSONField(
        default=dict,
        blank=True,
        db_comment="Transformation parameters",
        help_text="Parameters used to produce this artifact (deskew angle, dpi, ...).",
    )
    cache_key = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Scalar hash of source and processing policy; blank artifacts are not reusable.",
    )
    source_artifact = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
        related_name="derived_layouts",
        help_text="Exact derived input analyzed for this layout.",
    )
    page_map = models.JSONField(
        default=list,
        blank=True,
        db_comment="artifact page -> original page",
        help_text="Mapping so blank-page removal never breaks source references.",
    )
    service_name = models.CharField(
        max_length=64,
        blank=True,
        db_comment="Producing service",
        help_text="e.g. azure_document_intelligence, pypdf, openpyxl.",
    )
    service_version = models.CharField(
        max_length=64,
        blank=True,
        db_comment="Service/API version",
        help_text="API/model version that produced it.",
    )

    class Meta:
        db_table = "docai_processing_artifact"
        db_table_comment = "Immutable derived artifacts (layouts, normalized images, raw responses)"
        verbose_name = "processing artifact"
        verbose_name_plural = "processing artifacts"
        indexes = [
            models.Index(fields=["document", "kind"], name=ix("ix_docai_art_doc_kind")),
            models.Index(fields=["document", "kind", "cache_key"], name=ix("ix_docai_art_cache")),
            models.Index(fields=["sha256"], name=ix("ix_docai_art_hash")),
            models.Index(fields=["created"], name=ix("ix_docai_art_created")),
        ]


class SourceUnit(AuditedModel):
    """A page or a worksheet: the unit that spans, polygons and cell ranges
    reference. Normalized content lives in a layout artifact; this row keeps
    the identifiers, dimensions and a short text preview for search."""

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="units",
        db_comment="Owning document",
        help_text="Document.",
    )
    kind = models.CharField(
        max_length=8, choices=SOURCE_KIND, db_comment="page|sheet", help_text="Unit kind."
    )
    index = models.PositiveIntegerField(
        db_comment="0-based index within document", help_text="0-based index."
    )
    label = models.CharField(
        max_length=120,
        blank=True,
        db_comment="Sheet name or page label",
        help_text="Display label.",
    )
    width = models.FloatField(
        null=True, blank=True, db_comment="Page width", help_text="Width in `unit`."
    )
    height = models.FloatField(
        null=True, blank=True, db_comment="Page height", help_text="Height in `unit`."
    )
    unit = models.CharField(
        max_length=8, blank=True, db_comment="inch|pixel|point", help_text="Dimension unit."
    )
    row_count = models.PositiveIntegerField(
        null=True, blank=True, db_comment="Rows (sheets)", help_text="Rows."
    )
    col_count = models.PositiveIntegerField(
        null=True, blank=True, db_comment="Columns (sheets)", help_text="Columns."
    )
    layout_artifact = models.ForeignKey(
        ProcessingArtifact,
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
        related_name="units",
        db_comment="Normalized layout artifact",
        help_text="Artifact holding this unit's normalized layout.",
    )
    text_preview = models.TextField(
        blank=True,
        db_comment="First ~1000 chars (search)",
        help_text="Short text preview for search; not the full content.",
    )
    layout_storage_path = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Private immutable page/sheet layout artifact; avoids loading the complete layout for viewing.",
    )
    service_version = models.CharField(
        max_length=64,
        blank=True,
        db_comment="OCR/Layout API version",
        help_text="Service/API version that produced the layout.",
    )

    class Meta:
        db_table = "docai_source_unit"
        db_table_comment = "Pages/worksheets; the reference frame for all source mappings"
        verbose_name = "source unit"
        verbose_name_plural = "source units"
        ordering = ["document", "index"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "layout_artifact", "kind", "index"],
                name=ix("uq_docai_unit_layout_idx"),
            )
        ]
        indexes = [models.Index(fields=["document", "index"], name=ix("ix_docai_unit_doc_idx"))]

    def __str__(self):
        return f"{self.document_id}:{self.kind}{self.index}"
