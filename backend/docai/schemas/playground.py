"""Strict, content-free proposal produced by the workflow playground."""

import re
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from docai.schemas.config import FieldSpec


class ProposedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
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
    observed: bool
    sample_index: int | None = Field(
        default=None, description="Zero-based sample position: Sample 1 is index 0."
    )
    unit: int | None = Field(
        default=None,
        description="One-based page or sheet number printed in that sample: first is 1.",
    )
    source_label: str = ""
    variable_rows: bool = False
    guidance: str = ""
    enum_values: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_source(self):
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{1,79}", self.name)
            or not 2 <= len(self.description) <= 300
        ):
            raise PydanticCustomError(
                "playground_field_identity_invalid",
                "Field names need lower_snake_case and a short description",
            )
        if not self.observed:
            # Suggested fields carry no source claim; normalize model output to that invariant.
            self.sample_index = None
            self.unit = None
            self.source_label = ""
        if self.sample_index is not None and not 0 <= self.sample_index <= 2:
            raise PydanticCustomError(
                "playground_sample_index_invalid", "Sample index must be 0 through 2"
            )
        if self.unit is not None and not 1 <= self.unit <= 30:
            raise PydanticCustomError(
                "playground_source_unit_invalid", "Page or sheet number must be 1 through 30"
            )
        if len(self.source_label) > 120:
            raise PydanticCustomError(
                "playground_source_label_too_long", "Source labels must be short"
            )
        if len(self.guidance) > 500:
            raise PydanticCustomError(
                "playground_guidance_too_long", "Keep field guidance under 500 characters"
            )
        if self.observed and (
            self.sample_index is None or self.unit is None or not self.source_label
        ):
            raise PydanticCustomError(
                "playground_observed_source_missing",
                "Observed fields require a sample, page/sheet, and source label",
            )
        if self.type == "list" and not self.variable_rows:
            raise PydanticCustomError(
                "playground_list_requires_variable_rows",
                "Use separate scalar fields for fixed boxes; lists require variable rows",
            )
        if self.type == "list" and not self.guidance.strip():
            raise PydanticCustomError(
                "playground_list_guidance_missing",
                "List fields need guidance describing each variable row",
            )
        if self.type == "enum" and not 2 <= len(self.enum_values) <= 30:
            raise PydanticCustomError(
                "playground_enum_choices_invalid",
                "Enum fields need 2 to 30 explicit choices; use string otherwise",
            )
        if any(not 1 <= len(option.strip()) <= 100 for option in self.enum_values):
            raise PydanticCustomError(
                "playground_enum_choice_length_invalid", "Enum choices must be 1 to 100 characters"
            )
        if self.type != "enum" and self.enum_values:
            raise PydanticCustomError(
                "playground_enum_choices_unexpected", "Enum choices belong only to enum fields"
            )
        self.enum_values = [option.strip() for option in self.enum_values]
        return self


ALLOWED_FIELD_TYPES = get_args(FieldSpec.model_fields["type"].annotation)
RESERVED_BUNDLE_KEYS = {
    "needs_review",
    "other",
    "uncategorized",
    "uncategorized_document",
    "unclassified",
    "unknown",
    "unknown_document",
}


class ProposedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    description: str = ""
    distinguishing_evidence: str = ""
    continuation_characteristics: str = ""
    fields: list[ProposedField]

    @model_validator(mode="after")
    def bounded(self):
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,59}", self.key) or not 2 <= len(self.name) <= 100:
            raise PydanticCustomError(
                "playground_document_identity_invalid",
                "Document keys need lower_snake_case and a short name",
            )
        if (
            len(self.description) > 300
            or len(self.distinguishing_evidence) > 300
            or len(self.continuation_characteristics) > 300
        ):
            raise PydanticCustomError(
                "playground_document_description_too_long",
                "Document descriptions and bundle cues must be 300 characters or fewer",
            )
        if not 1 <= len(self.fields) <= 120:
            raise PydanticCustomError(
                "playground_document_field_count_invalid",
                "Each document type needs 1 to 120 fields",
            )
        return self


class PlaygroundProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_type: Literal[
        "extract_structured", "extract_unstructured", "unbundle_classify_extract"
    ]
    documents: list[ProposedDocument]

    @model_validator(mode="before")
    @classmethod
    def remove_reserved_bundle_categories(cls, data: Any):
        """The compiler owns the catch-all review route; it is not an extraction schema."""
        if not isinstance(data, dict) or data.get("workflow_type") != "unbundle_classify_extract":
            return data
        documents = data.get("documents")
        if not isinstance(documents, list):
            return data
        filtered = [
            document
            for document in documents
            if not (
                isinstance(document, dict)
                and str(document.get("key", "")).strip().lower() in RESERVED_BUNDLE_KEYS
            )
        ]
        return {**data, "documents": filtered}

    @model_validator(mode="after")
    def consistent(self):
        if not 1 <= len(self.documents) <= 12:
            raise PydanticCustomError(
                "playground_document_count_invalid", "Proposal needs 1 to 12 document types"
            )
        if self.workflow_type != "unbundle_classify_extract" and len(self.documents) != 1:
            raise PydanticCustomError(
                "playground_single_document_count_invalid",
                "Single-document workflows require exactly one document type",
            )
        if len({document.key for document in self.documents}) != len(self.documents):
            raise PydanticCustomError(
                "playground_document_keys_duplicate", "Document keys must be unique"
            )
        if self.workflow_type == "unbundle_classify_extract":
            for document in self.documents:
                if not all(
                    value.strip()
                    for value in (
                        document.description,
                        document.distinguishing_evidence,
                        document.continuation_characteristics,
                    )
                ):
                    raise PydanticCustomError(
                        "playground_bundle_cues_missing",
                        "Each bundled document type needs a description, distinguishing evidence, and continuation characteristics",
                    )
        for document in self.documents:
            if len({field.name for field in document.fields}) != len(document.fields):
                raise PydanticCustomError(
                    "playground_field_names_duplicate",
                    "Field names must be unique within each document",
                )
        return self


def compile_proposal(proposal: PlaygroundProposal) -> dict:
    """Only the compiler emits workflow JSON; model output is never pasted verbatim."""
    schemas = [
        {
            "name": document.key,
            "fields": [
                FieldSpec(
                    name=field.name,
                    description=field.description,
                    type=field.type,
                    required=field.required,
                    guidance=field.guidance,
                    enum=field.enum_values,
                ).model_dump(exclude_defaults=True)
                for field in document.fields
            ],
        }
        for document in proposal.documents
    ]
    routing = [{"when": {}, "outcome": "human_review"}]
    if proposal.workflow_type == "unbundle_classify_extract":
        return {
            "categories": [
                {
                    "key": document.key,
                    "name": document.name,
                    "description": document.description,
                    "distinguishing_evidence": document.distinguishing_evidence,
                    "continuation_characteristics": document.continuation_characteristics,
                    "extraction_schema": document.key,
                }
                for document in proposal.documents
            ],
            "schemas": schemas,
            "other_behavior": "needs_review",
            "routing": routing,
        }
    return (
        {
            "mode": "custom" if proposal.workflow_type == "extract_structured" else None,
            "document_type": proposal.documents[0].key,
            "schema": schemas[0],
            "routing": routing,
        }
        if proposal.workflow_type == "extract_structured"
        else {
            "document_type": proposal.documents[0].key,
            "schema": schemas[0],
            "routing": routing,
        }
    )
