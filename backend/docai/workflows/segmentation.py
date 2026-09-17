"""Bounded document identification with explicit, inspectable boundary decisions.

Windows vote about *adjacent page identity*, never merely category equality.
A disagreement gets one local adjudication. Missing/invalid evidence stays
provisional; this module neither persists results nor repairs coverage silently.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from docai.adapters.llm.base import LLMCall
from docai.exceptions import InvalidModelOutput
from docai.grounding.sources import validate_sources
from docai.schemas.config import SegmentationConfig
from docai.schemas.layout import LayoutDocument
from docai.schemas.llm import SegmentationOut

from .base import DocumentResult, WorkflowContext

UNCERTAIN = "SEGMENTATION_BOUNDARY_UNCERTAIN"
REPAIRED = "SEGMENTATION_BOUNDARY_REPAIRED"


@dataclass
class Proposal:
    start: int
    end: int
    category: str
    confidence: float | None = None
    evidence: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass
class IdentifiedDocument:
    start: int
    end: int
    category: str
    confidence: float | None
    evidence: str
    sources: list[dict[str, Any]]
    boundary: dict[str, Any]
    review_reasons: list[str]


def page_evidence(text: str, limit: int) -> tuple[str, bool]:
    """Sample intact lines across the page; do not manufacture truncated source IDs."""
    if len(text) <= limit:
        return text, False
    marker = "\n[PAGE EVIDENCE INCOMPLETE: omitted content]\n"
    allowance = max(0, (limit - len(marker) * 2) // 3)
    lines = text.splitlines()
    groups: list[str] = []
    for start in (0, len(lines) // 2, max(0, len(lines) - max(1, len(lines) // 4))):
        selected: list[str] = []
        used = 0
        for line in lines[start:]:
            if used + len(line) + 1 > allowance:
                break
            selected.append(line)
            used += len(line) + 1
        groups.append("\n".join(selected))
    return marker.join(groups), True


def _call(
    ctx: WorkflowContext,
    categories: str,
    evidence: dict[int, str],
    indexes: list[int],
    *,
    boundary: bool = False,
) -> LLMCall:
    instructions = (
        "BOUNDARY CHECK: Decide whether these two adjacent analyzed pages belong to one "
        "document instance or two. Category equality is insufficient. Return one segment only "
        "with positive continuation evidence; otherwise return two and flag uncertainty.\n"
        if boundary
        else ""
    )
    call = ctx.call(
        "segmentation",
        schema=SegmentationOut,
        schema_name="SegmentationOut",
        schema_version=2,
        fmt={
            "categories": categories,
            "units": instructions
            + "\n".join(f"[original unit {index}]\n{evidence[index]}" for index in indexes),
        },
        mock_context={
            "unit_texts": [evidence[index] for index in indexes],
            "unit_indexes": indexes,
            "categories": [c.key for c in ctx.config.categories],
        },
        chunk_index=indexes[0],
    )
    call.parameters["max_tokens"] = ctx.config.segmentation.output_tokens
    return call


def request_size(call: LLMCall, settings: SegmentationConfig) -> int:
    return (
        len(call.system)
        + len(call.user)
        + len(json.dumps(SegmentationOut.model_json_schema()))
        + settings.output_tokens * 4
    )


def _proposals(
    ctx: WorkflowContext,
    layout: LayoutDocument,
    call: LLMCall,
    indexes: list[int],
    result: DocumentResult,
    window: dict[str, Any],
) -> tuple[list[Proposal], list[str]]:
    try:
        response = ctx.invoke(call)
        parsed = response.parsed
        result.raw_responses.append(
            {
                "stage": "segmentation",
                "window": window,
                "deployment": response.model_deployment,
                "latency_ms": response.latency_ms,
            }
        )
    except InvalidModelOutput as exc:
        ctx.discard_checkpoint(call)
        result.warnings.append(f"segmentation: {exc.error_code}; boundaries require review")
        return [], ["invalid_model_output"]
    # Match complete citation tokens in the supplied unit evidence. Substrings such
    # as p1:l1 inside p1:l10 must not authenticate an omitted source.
    supplied_ids = {
        index: {
            token
            for marker in re.findall(r"\[([^\]\n]+)\]", text)
            for token in re.findall(r"[\w.-]+(?::[\w.-]+)*", marker)
        }
        | set(re.findall(r"\b[A-Z]+[1-9][0-9]*(?==)", text))
        for index, text in zip(
            call.mock_context["unit_indexes"], call.mock_context["unit_texts"], strict=True
        )
    }
    proposals: list[Proposal] = []
    global_reasons: list[str] = []
    starts = [segment.start_unit for segment in parsed.segments]
    if starts != sorted(starts):
        global_reasons.append("unordered_proposals")
    allowed = set(indexes)
    categories = {c.key for c in ctx.config.categories}
    for segment in parsed.segments:
        reasons = []
        if segment.start_unit not in allowed or segment.end_unit not in allowed:
            reasons.append("out_of_window_range")
        if segment.continuation_of is not None:
            # Noncontiguous identity is deliberately unsupported in this iteration.
            reasons.append("unsupported_continuation_reference")
        if segment.end_unit > segment.start_unit and not (segment.evidence or segment.sources):
            reasons.append("missing_continuation_evidence")
        if segment.confidence is None or segment.confidence < 0.5:
            reasons.append("low_boundary_confidence")
        if segment.boundary_uncertain:
            reasons.append("ambiguous_document_identity")
        if segment.category not in categories:
            reasons.append("unknown_category")
        try:
            validate_sources(
                layout,
                segment.sources,
                allowed_indexes={
                    index for index in indexes if segment.start_unit <= index <= segment.end_unit
                },
            )
            if any(
                source_id not in supplied_ids.get(source.unit_index, set())
                for source in segment.sources
                for source_id in source.ids
            ):
                raise InvalidModelOutput(
                    errors={"sources": "Citation was not supplied in this window."}
                )
            sources = [source.model_dump() for source in segment.sources]
        except InvalidModelOutput:
            ctx.discard_checkpoint(call)
            reasons.append("invalid_source")
            sources = []
        if not any(segment.start_unit <= index <= segment.end_unit for index in indexes):
            global_reasons.append("out_of_window_range")
            continue
        proposals.append(
            Proposal(
                segment.start_unit,
                segment.end_unit,
                segment.category,
                segment.confidence,
                segment.evidence,
                sources,
                reasons,
            )
        )
    return proposals, global_reasons


def identify_documents(
    ctx: WorkflowContext,
    layout: LayoutDocument,
    texts: list[str],
    result: DocumentResult,
) -> list[IdentifiedDocument]:
    settings = ctx.config.segmentation
    categories = "\n".join(
        f"- {c.key}: {c.name}. {c.description} Evidence: {c.distinguishing_evidence}. "
        f"Aliases: {', '.join(c.aliases)}. Continuations: {c.continuation_characteristics}"
        for c in ctx.config.categories
    )
    excluded = {p.index for p in layout.pages if p.excluded_from_analysis}
    indexes = sorted(unit.index for unit in layout.units if unit.index not in excluded)
    evidence: dict[int, str] = {}
    reasons: dict[int, set[str]] = {index: set() for index in indexes}
    votes: dict[int, list[Proposal]] = {index: [] for index in indexes}
    edges: dict[tuple[int, int], list[bool]] = {}
    windows: list[dict[str, Any]] = []
    decisions: dict[tuple[int, int], str] = {}
    for unit, text in zip(layout.units, texts, strict=True):
        if unit.index in excluded:
            continue
        evidence[unit.index], truncated = page_evidence(text, settings.page_chars)
        if truncated:
            reasons[unit.index].add("incomplete_page_evidence")
    cursor = 0
    while cursor < len(indexes):
        selected: list[int] = []
        for index in indexes[cursor : cursor + settings.window_pages]:
            candidate = [*selected, index]
            call = _call(ctx, categories, evidence, candidate)
            if request_size(call, settings) > settings.request_budget_chars:
                break
            selected = candidate
        if not selected:
            reasons[indexes[cursor]].add("request_budget_exceeded")
            cursor += 1
            continue
        call = _call(ctx, categories, evidence, selected)
        ctx.report_progress("analyzing", "identifying_groups")
        window = {"start": selected[0], "end": selected[-1], "purpose": "window"}
        windows.append(window)
        proposals, issues = _proposals(ctx, layout, call, selected, result, window)
        memberships: dict[int, list[Proposal]] = {}
        for index in selected:
            members = [p for p in proposals if p.start <= index <= p.end]
            memberships[index] = members
            votes[index].extend(members)
            reasons[index].update(issues)
            if len(members) != 1:
                reasons[index].add("overlapping_proposals" if members else "uncovered_page")
            for proposal in members:
                reasons[index].update(proposal.reasons)
        for left, right in zip(selected, selected[1:], strict=False):
            a, b = memberships[left], memberships[right]
            if len(a) == len(b) == 1 and not a[0].reasons and not b[0].reasons:
                edges.setdefault((left, right), []).append(a[0] is b[0])
        if cursor + len(selected) == len(indexes):
            break
        cursor += max(1, len(selected) - min(settings.overlap_pages, len(selected) - 1))

    joined: dict[tuple[int, int], bool] = {}
    for left, right in zip(indexes, indexes[1:], strict=False):
        edge = (left, right)
        edge_votes = edges.get(edge, [])
        disagree = not edge_votes or len(set(edge_votes)) > 1
        if not disagree:
            joined[edge] = edge_votes[0]
            decisions[edge] = "window_agreement"
            continue
        # At most one new request for each disputed boundary; never expand to the bundle.
        call = _call(ctx, categories, evidence, [left, right], boundary=True)
        window = {"start": left, "end": right, "purpose": "boundary"}
        resolved = False
        if request_size(call, settings) <= settings.request_budget_chars:
            windows.append(window)
            proposals, issues = _proposals(ctx, layout, call, [left, right], result, window)
            a = [p for p in proposals if p.start <= left <= p.end]
            b = [p for p in proposals if p.start <= right <= p.end]
            if len(a) == len(b) == 1 and not issues and not a[0].reasons and not b[0].reasons:
                # Boundary-only calls may not silently reclassify established page evidence.
                agrees = all(
                    all(v.category == proposal.category for v in votes[index])
                    for index, proposal in ((left, a[0]), (right, b[0]))
                )
                if agrees:
                    joined[edge] = a[0] is b[0]
                    resolved = True
        decisions[edge] = "boundary_adjudication" if resolved else "unresolved_boundary"
        if not resolved:
            joined[edge] = False
            reasons[left].add("unresolved_window_boundary")
            reasons[right].add("unresolved_window_boundary")

    groups: list[list[int]] = []
    for index in indexes:
        if groups and joined.get((groups[-1][-1], index), False):
            previous = groups[-1][-1]
            cats = {p.category for i in (previous, index) for p in votes[i]}
            if len(cats) == 1:
                groups[-1].append(index)
                continue
            reasons[previous].add("category_disagreement")
            reasons[index].add("category_disagreement")
        groups.append([index])
    return [
        _finalize(group, votes, reasons, excluded, windows, decisions, settings) for group in groups
    ]


def _finalize(
    group: list[int],
    votes: dict[int, list[Proposal]],
    reasons: dict[int, set[str]],
    excluded: set[int],
    windows: list[dict[str, Any]],
    decisions: dict[tuple[int, int], str],
    settings: SegmentationConfig,
) -> IdentifiedDocument:
    # A proposal votes for several pages; preserve it once in the audit metadata.
    proposals = list({id(p): p for index in group for p in votes[index]}.values())
    categories_seen = {p.category for p in proposals}
    issues = {reason for index in group for reason in reasons[index]}
    category = next(iter(categories_seen)) if len(categories_seen) == 1 else "other"
    if len(categories_seen) > 1:
        issues.add("category_disagreement")
    if not proposals:
        issues.add("uncovered_page")
    unique_ranges = sorted({(p.start, p.end) for p in proposals})
    representative = proposals[0] if proposals else None
    sources = list(
        {
            json.dumps(source, sort_keys=True): source
            for p in proposals
            for source in p.sources
            if source["unit_index"] in group
        }.values()
    )
    repair = bool(
        issues
        & {
            "overlapping_proposals",
            "unordered_proposals",
            "uncovered_page",
            "out_of_window_range",
            "unsupported_continuation_reference",
        }
    )
    review_reasons = ([UNCERTAIN] if issues else []) + ([REPAIRED] if repair else [])
    boundary = {
        "proposed_ranges": [list(pair) for pair in unique_ranges],
        "proposals": [
            {
                "range": [p.start, p.end],
                "category": p.category,
                "confidence": p.confidence,
                "reasons": p.reasons,
            }
            for p in proposals
        ],
        "effective_range": [group[0], group[-1]],
        "reasons": sorted(issues),
        "excluded_unit_indexes": sorted(excluded),
        "windows": [
            window
            for window in windows
            if window["start"] <= group[-1] and window["end"] >= group[0]
        ],
        "decisions": [
            {"between": list(edge), "decision": decision}
            for edge, decision in decisions.items()
            if group[0] <= edge[1] and edge[0] <= group[-1]
        ],
        "settings": settings.model_dump(),
    }
    return IdentifiedDocument(
        group[0],
        group[-1],
        category,
        representative.confidence if representative else None,
        representative.evidence if representative else "",
        sources,
        boundary,
        review_reasons,
    )
