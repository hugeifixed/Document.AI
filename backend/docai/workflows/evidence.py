"""Assess extraction evidence and enforce the resulting trust decisions.

Reconciliation may copy a candidate to lower its confidence. Its citation validity
and checkbox scope still belong to the original submitted candidate. This module
owns that provenance; callers choose values, validate them, and receive one final
grounding/validation/review decision.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field

from loguru import logger

from docai.adapters.llm.base import LLMCall
from docai.exceptions import InvalidModelOutput
from docai.grounding.locate import locate_in_page, locate_in_sheet
from docai.grounding.properties import ground_properties
from docai.grounding.selection_marks import ground_selection_mark
from docai.grounding.sources import cited_unit, source_elements, validate_sources
from docai.schemas.layout import LayoutDocument, LayoutPage
from docai.schemas.llm import FieldOut, StructuredResult
from docai.validation.collections import LIST_CONFLICT, LIST_REVIEW
from docai.validation.rules import ValidationOutcome

from .base import WorkflowContext
from .routing import route


def ground(
    layout: LayoutDocument,
    f: FieldOut,
    unit_hint: int | None,
    *,
    allowed_indexes: set[int] | None = None,
) -> dict | None:
    if f.value in (None, ""):
        return None
    try:
        validate_sources(layout, f.sources, unit_index=unit_hint, allowed_indexes=allowed_indexes)
    except InvalidModelOutput:
        return None
    claimed, hit = ground_selection_mark(layout, f, unit_hint, allowed_indexes=allowed_indexes)
    if claimed:
        return hit
    units = {
        unit.index: unit
        for unit in layout.units
        if not (isinstance(unit, LayoutPage) and unit.excluded_from_analysis)
        and (allowed_indexes is None or unit.index in allowed_indexes)
    }
    # Explicit citations bound the search. Never substitute another occurrence of
    # a repeated value on an uncited page, or outside this extraction segment.
    order = list(dict.fromkeys(source.unit_index for source in f.sources))
    if unit_hint is not None:
        order = [unit_hint] + [index for index in order if index != unit_hint]
    for index in order or list(units):
        ids = {
            source_id
            for source in f.sources
            if source.unit_index == index
            for source_id in source.ids
        }
        unit = cited_unit(units[index], ids)
        hit = (
            locate_in_page(f.value, unit, f.evidence)
            if isinstance(unit, LayoutPage)
            else locate_in_sheet(f.value, unit)
        )
        if hit:
            return {"unit_index": index, **hit}
    return None


EVIDENCE_REVIEW_MESSAGE = "The model cited an unavailable document location. Verify this value against the original document."


@dataclass(frozen=True)
class EvidenceDecision:
    grounding: dict | None
    validation: ValidationOutcome
    review_outcome: str
    property_evidence: list[dict] = dataclass_field(default_factory=list)


@dataclass(frozen=True)
class _CandidateEvidence:
    # Retain the original object so its identity cannot be recycled between chunks.
    candidate: FieldOut
    invalid: bool
    checkbox_claimed: bool
    checkbox_hit: dict | None
    allowed_indexes: set[int]
    repaired: bool
    repaired_properties: set[str]


class ExtractionEvidence:
    """One extraction's evidence, from submitted chunks through final routing.

    ``scalar_indexes`` is the caller's search scope: the whole extraction segment
    for schema fields, the submitted chunk for generic pairs. Source validation
    and checkbox grounding always use the narrower submitted chunk scope.
    """

    def __init__(self, ctx: WorkflowContext, layout: LayoutDocument, *, scalar_indexes: set[int]):
        self._ctx = ctx
        self._layout = layout
        self._scalar_indexes = set(scalar_indexes)
        self._candidates: dict[int, _CandidateEvidence] = {}

    def inspect_chunk(
        self,
        fields: list[FieldOut],
        allowed_indexes: set[int],
        call: LLMCall,
        response: StructuredResult,
        *,
        repaired_ids: set[int] | None = None,
        repaired_properties: dict[int, set[str]] | None = None,
    ) -> int:
        """Capture provenance before reconciliation; report how many citations failed."""
        issues = []
        for index, candidate in enumerate(fields):
            rejected = False
            try:
                validate_sources(
                    self._layout,
                    candidate.sources,
                    unit_index=candidate.unit_index,
                    allowed_indexes=allowed_indexes,
                )
            except InvalidModelOutput as exc:
                rejected = True
                issues.append({"field_index": index, **exc.diagnostics})
            claimed, hit = (
                (False, None)
                if rejected
                else ground_selection_mark(
                    self._layout, candidate, candidate.unit_index, allowed_indexes=allowed_indexes
                )
            )
            self._candidates[id(candidate)] = _CandidateEvidence(
                candidate,
                rejected,
                claimed,
                hit,
                set(allowed_indexes),
                id(candidate) in (repaired_ids or set()),
                set((repaired_properties or {}).get(id(candidate), set())),
            )
        if issues:
            _report_invalid_sources(
                self._ctx, self._layout, fields, allowed_indexes, call, response, issues
            )
        return len(issues)

    def decide(
        self,
        field: FieldOut,
        *,
        selected_candidate: FieldOut | None = None,
        field_type: str = "string",
        validation: ValidationOutcome | None = None,
        conflict: bool = False,
    ) -> EvidenceDecision:
        """Apply evidence constraints after value selection and ordinary validation.

        Pass reconciliation's original ``selected_candidate`` if ``field`` is a
        copy. A synthetic absent schema field needs no submitted candidate.
        Configurable routing cannot override invalid citations or list review.
        """
        original = selected_candidate if selected_candidate is not None else field
        assessment = self._candidates.get(id(original))
        if assessment is None and field.value not in (None, ""):
            raise ValueError("Inspect the selected candidate before deciding its evidence")
        invalid = bool(assessment and assessment.invalid)
        grounding = None
        property_evidence = (
            ground_properties(self._layout, field, assessment.allowed_indexes)
            if field_type == "list" and assessment
            else []
        )
        if assessment:
            for prop in property_evidence:
                if prop["path"] in assessment.repaired_properties:
                    prop["citation_repaired"] = True
        if not invalid and field_type != "list":
            if assessment and assessment.checkbox_claimed:
                grounding = assessment.checkbox_hit
            else:
                grounding = ground(
                    self._layout, field, field.unit_index, allowed_indexes=self._scalar_indexes
                )
        # Keep the caller's schema validation intact, including correction hints.
        outcome = (
            replace(validation, messages=list(validation.messages))
            if validation
            else ValidationOutcome(status="not_run")
        )
        review = route(
            self._ctx.config.routing,
            field=field.name,
            score=field.confidence,
            grounded=grounding is not None,
            validation_status=validation.status if validation else "passed",
            disagreement=conflict,
        )
        if field_type == "list" and field.value not in (None, ""):
            review = "human_review"
            outcome.messages.append(LIST_REVIEW)
            if outcome.status == "passed":
                outcome.status = "warning"
            if conflict:
                outcome.messages.append(LIST_CONFLICT)
            if any(
                p["status"] in {"invalid_reference", "invalid_path", "duplicate_path"}
                for p in property_evidence
            ):
                outcome.status = "failed"
                outcome.messages.append(
                    "Some list property citations identify invalid or duplicate locations. Verify the affected properties."
                )
        if assessment and assessment.repaired:
            review = "human_review"
            outcome.messages.append(
                "Source citations were corrected in one bounded retry. Verify the unchanged value and its record association."
            )
            if outcome.status in {"passed", "not_run"}:
                outcome.status = "warning"
            if grounding:
                grounding = {**grounding, "citation_repaired": True}
        if invalid:
            outcome.messages.append(EVIDENCE_REVIEW_MESSAGE)
            outcome.status = "failed"
            review = "human_review"
        return EvidenceDecision(grounding, outcome, review, property_evidence)


def _report_invalid_sources(
    ctx: WorkflowContext,
    layout: LayoutDocument,
    fields: list[FieldOut],
    allowed_indexes: set[int],
    call: LLMCall,
    response: StructuredResult,
    issues: list[dict],
) -> None:
    """Keep diagnostics best effort and separate from the evidence decision."""
    logger.bind(
        event="extraction_evidence_invalid",
        stage=call.stage,
        chunk_index=call.chunk_index,
        segment_index=call.segment_index,
        invalid_fields=len(issues),
        validation_reasons=sorted({issue["validation_reason"] for issue in issues}),
        total_fields=len(fields),
    ).warning("Fields with invalid evidence require review")
    if ctx.debug_capture is not None:
        try:
            ctx.debug_capture(
                {
                    "stage": call.stage,
                    "chunk_index": call.chunk_index,
                    "segment_index": call.segment_index,
                    "issues": issues,
                    "prompt_name": call.prompt_name,
                    "prompt_version": call.prompt_version,
                    "deployment": response.model_deployment,
                    "submitted_content": call.user,
                    "parsed_response": response.parsed.model_dump(mode="json"),
                    "raw_response": response.raw_response,
                    "allowed_source_ids": {
                        str(unit.index): sorted(source_elements(unit))
                        for unit in layout.units
                        if unit.index in allowed_indexes
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001 -- diagnostics must not affect processing
            logger.bind(event="llm_debug_capture_failed", error_type=type(exc).__name__).warning(
                "Local LLM debug capture failed"
            )
