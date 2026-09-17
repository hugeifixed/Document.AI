"""Business-document identity, bounded prompts, and honest malformed-output handling."""

import pytest
from pydantic import ValidationError

from docai.adapters.llm.mock import MockStructuredLLM
from docai.exceptions import InvalidModelOutput
from docai.schemas.config import UnbundleClassifyExtractConfig
from docai.schemas.layout import LayoutDocument, LayoutPage
from docai.schemas.llm import SegmentationOut, SegmentOut, SourceRef, StructuredResult
from docai.workflows.base import DocumentResult, PromptRef, WorkflowContext
from docai.workflows.prompts import SEGMENT_SYSTEM, SEGMENT_USER
from docai.workflows.segmentation import REPAIRED, UNCERTAIN, identify_documents, request_size


def context(provider, **segmentation):
    return WorkflowContext(
        workflow_type="unbundle_classify_extract",
        config=UnbundleClassifyExtractConfig.model_validate(
            {
                "categories": [{"key": "w2", "name": "W-2"}, {"key": "note", "name": "Note"}],
                "segmentation": {"window_pages": 4, "overlap_pages": 2, **segmentation},
            }
        ),
        llm=provider,
        prompts={
            "segmentation": PromptRef("bounded-segmentation", 1, SEGMENT_SYSTEM, SEGMENT_USER)
        },
        layout_adapter_key="fixture",
    )


def layout(count, excluded=()):
    return LayoutDocument(
        document_id="fixture",
        source_format="pdf",
        service="fixture",
        units=[
            LayoutPage(index=i, number=i + 1, excluded_from_analysis=i in excluded)
            for i in range(count)
        ],
    )


class ManifestProvider:
    key = "fixture"

    def __init__(self, manifest):
        self.manifest = manifest
        self.calls = []

    def invoke(self, call):
        self.calls.append(call)
        indexes = call.mock_context["unit_indexes"]
        segments = [
            SegmentOut(
                start_unit=max(start, indexes[0]),
                end_unit=min(end, indexes[-1]),
                category=category,
                confidence=0.9,
                evidence="Document title and continuation page numbering",
            )
            for start, end, category in self.manifest
            if start <= indexes[-1] and end >= indexes[0]
        ]
        return StructuredResult(
            parsed=SegmentationOut(segments=segments), raw_response="{}", model_deployment="fixture"
        )


def test_repeated_forms_and_long_notes_keep_independent_original_instances():
    expected = [(0, 0, "w2"), (1, 1, "w2"), (2, 12, "note"), (13, 13, "w2"), (14, 20, "note")]
    provider = ManifestProvider(expected)
    ctx = context(provider)
    docs = identify_documents(ctx, layout(21), ["page"] * 21, DocumentResult())
    assert [(d.start, d.end, d.category) for d in docs] == expected
    assert not any(d.review_reasons for d in docs)
    assert len(provider.calls) > 1
    assert all(len(call.mock_context["unit_indexes"]) <= 4 for call in provider.calls)
    assert all(request_size(call, ctx.config.segmentation) <= 60000 for call in provider.calls)


def test_six_hundred_pages_have_bounded_requests_and_original_indexes():
    provider = ManifestProvider([(0, 299, "note"), (300, 300, "w2"), (301, 599, "note")])
    ctx = context(provider, window_pages=12)
    docs = identify_documents(ctx, layout(600), ["page"] * 600, DocumentResult())
    assert [(d.start, d.end) for d in docs] == [(0, 299), (300, 300), (301, 599)]
    assert max(len(call.mock_context["unit_indexes"]) for call in provider.calls) == 12
    assert len(provider.calls) == 60
    assert all(request_size(call, ctx.config.segmentation) <= 60000 for call in provider.calls)


def test_gaps_are_explicit_unresolved_instances_not_confident_neighbor_extensions():
    provider = ManifestProvider([(1, 1, "w2"), (3, 3, "note")])
    docs = identify_documents(context(provider), layout(4), ["page"] * 4, DocumentResult())
    assert [(d.start, d.end) for d in docs] == [(0, 0), (1, 1), (2, 2), (3, 3)]
    assert docs[0].category == "other"
    assert docs[0].confidence is None
    assert REPAIRED in docs[0].review_reasons
    assert docs[1].confidence == 0.9


def test_excluded_blank_keeps_original_page_numbers_without_invented_document():
    provider = ManifestProvider([(0, 3, "note"), (4, 4, "w2")])
    docs = identify_documents(
        context(provider), layout(5, excluded=(1,)), ["page"] * 5, DocumentResult()
    )
    assert [(d.start, d.end) for d in docs] == [(0, 3), (4, 4)]
    assert docs[0].boundary["excluded_unit_indexes"] == [1]
    assert all(1 not in call.mock_context["unit_indexes"] for call in provider.calls)


def test_dense_single_line_is_flagged_and_never_exceeds_prompt_budget():
    provider = ManifestProvider([(0, 0, "w2")])
    ctx = context(provider, page_chars=500)
    docs = identify_documents(ctx, layout(1), ["value [p1:w1]" * 5000], DocumentResult())
    assert docs[0].review_reasons == [UNCERTAIN]
    assert "incomplete_page_evidence" in docs[0].boundary["reasons"]
    assert request_size(provider.calls[0], ctx.config.segmentation) < 60000


def test_categories_and_full_prompt_overhead_can_prevent_provider_call():
    provider = ManifestProvider([(0, 0, "w2")])
    ctx = context(provider)
    ctx.config.categories[0].description = "x" * 60000
    docs = identify_documents(ctx, layout(1), ["page"], DocumentResult())
    assert not provider.calls
    assert "request_budget_exceeded" in docs[0].boundary["reasons"]


class DisagreeingProvider(ManifestProvider):
    def invoke(self, call):
        if "BOUNDARY CHECK" in call.user:
            response = super().invoke(call)
            response.parsed.segments[0].boundary_uncertain = True
            return response
        indexes = call.mock_context["unit_indexes"]
        if indexes[0] == 0:
            self.calls.append(call)
            return StructuredResult(
                parsed=SegmentationOut(
                    segments=[
                        SegmentOut(
                            start_unit=0,
                            end_unit=3,
                            category="note",
                            confidence=0.9,
                            evidence="Note continuation",
                        )
                    ]
                ),
                raw_response="{}",
                model_deployment="fixture",
            )
        return super().invoke(call)


def test_window_disagreement_gets_one_boundary_call_then_explicit_review():
    provider = DisagreeingProvider([(0, 2, "note"), (3, 5, "note")])
    docs = identify_documents(context(provider), layout(6), ["page"] * 6, DocumentResult())
    boundary_calls = [call for call in provider.calls if "BOUNDARY CHECK" in call.user]
    assert len(boundary_calls) == 1
    assert boundary_calls[0].mock_context["unit_indexes"] == [2, 3]
    assert [(d.start, d.end) for d in docs] == [(0, 2), (3, 5)]
    assert all(UNCERTAIN in d.review_reasons for d in docs)


def test_mock_obeys_original_window_indexes():
    provider = MockStructuredLLM()
    docs = identify_documents(
        context(provider), layout(8), ["Form W-2 Wage and Tax Statement"] * 8, DocumentResult()
    )
    assert docs[-1].end == 7


@pytest.mark.parametrize(
    "change",
    [
        {"segmentation_strategy": "page"},
        {"segmentation": {"window_pages": 2, "overlap_pages": 2}},
        {"segmentation": {"imaginary_option": 1}},
        {"segmentation": {"request_budget_chars": 12000, "output_tokens": 4000}},
    ],
)
def test_ineffective_or_invalid_settings_rejected(change):
    with pytest.raises(ValidationError):
        UnbundleClassifyExtractConfig.model_validate(
            {"categories": [{"key": "w2", "name": "W2"}], **change}
        )


class InvalidProvider:
    key = "fixture"

    def invoke(self, call):
        raise InvalidModelOutput(errors={"segments": "invalid"})


def test_invalid_response_preserves_unresolved_pages_without_whole_bundle_fallback():
    result = DocumentResult()
    docs = identify_documents(context(InvalidProvider()), layout(3), ["page"] * 3, result)
    assert [(d.start, d.end) for d in docs] == [(0, 0), (1, 1), (2, 2)]
    assert all(REPAIRED in d.review_reasons for d in docs)
    assert result.warnings


class FixedProvider:
    key = "fixture"

    def __init__(self, segments):
        self.segments = segments
        self.calls = []

    def invoke(self, call):
        self.calls.append(call)
        return StructuredResult(
            parsed=SegmentationOut(segments=self.segments),
            raw_response="{}",
            model_deployment="fixture",
        )


@pytest.mark.parametrize(
    "segments,reason",
    [
        (
            [SegmentOut(start_unit=0, end_unit=9, category="w2", confidence=0.9)],
            "out_of_window_range",
        ),
        (
            [
                SegmentOut(start_unit=0, end_unit=1, category="w2", confidence=0.9),
                SegmentOut(start_unit=1, end_unit=1, category="note", confidence=0.9),
            ],
            "overlapping_proposals",
        ),
        (
            [
                SegmentOut(
                    start_unit=0, end_unit=1, category="note", confidence=0.9, continuation_of=99
                )
            ],
            "unsupported_continuation_reference",
        ),
        (
            [
                SegmentOut(
                    start_unit=0,
                    end_unit=1,
                    category="note",
                    confidence=0.9,
                    sources=[SourceRef(unit_index=0, ids=["p2:w1"])],
                )
            ],
            "invalid_source",
        ),
    ],
)
def test_malformed_proposals_preserve_review_provenance(segments, reason):
    docs = identify_documents(
        context(FixedProvider(segments)), layout(2), ["page"] * 2, DocumentResult()
    )
    assert {index for d in docs for index in range(d.start, d.end + 1)} == {0, 1}
    assert any(reason in d.boundary["reasons"] for d in docs)
    assert all(UNCERTAIN in d.review_reasons for d in docs)
    assert all(d.boundary["proposed_ranges"] for d in docs)


def test_window_disagreement_can_be_resolved_without_merging_same_category_instances():
    class ResolvedProvider(DisagreeingProvider):
        def invoke(self, call):
            if "BOUNDARY CHECK" in call.user:
                return ManifestProvider.invoke(self, call)
            return super().invoke(call)

    provider = ResolvedProvider([(0, 2, "note"), (3, 5, "note")])
    docs = identify_documents(context(provider), layout(6), ["page"] * 6, DocumentResult())
    assert [(d.start, d.end) for d in docs] == [(0, 2), (3, 5)]
    assert not any(d.review_reasons for d in docs)
    assert any(
        decision["decision"] == "boundary_adjudication"
        for d in docs
        for decision in d.boundary["decisions"]
    )


def test_all_excluded_pages_produce_no_invented_instance_or_provider_call():
    provider = ManifestProvider([])
    assert (
        identify_documents(
            context(provider), layout(2, excluded=(0, 1)), ["", ""], DocumentResult()
        )
        == []
    )
    assert not provider.calls


def test_unbundle_forces_classification_and_extraction_review_on_boundary_ambiguity(monkeypatch):
    from docai.schemas.config import ExtractionSchemaConfig
    from docai.workflows import unbundle
    from docai.workflows.base import FieldResultData

    provider = FixedProvider(
        [
            SegmentOut(
                start_unit=0, end_unit=0, category="w2", confidence=0.95, boundary_uncertain=True
            )
        ]
    )
    ctx = context(provider)
    ctx.config.categories[0].extraction_schema = "w2"
    ctx.config.schemas = [ExtractionSchemaConfig(name="w2", fields=[])]

    def extract(*args, result, segment_index, unit_texts, **kwargs):
        assert segment_index == 0
        assert len(unit_texts) == 1
        result.fields.append(
            FieldResultData(
                name="wages",
                field_type="currency",
                raw_value="100",
                normalized_value="100",
                score=0.99,
                source_text="100",
                method="llm",
                strategy="whole_document",
                fallback_used="",
                model_deployment="fixture",
                prompt=None,
                schema=None,
                api_version="",
                validation_status="valid",
                validation_messages=[],
                suggested_correction=None,
                grounding=None,
                review_outcome="accepted",
                segment_index=segment_index,
            )
        )

    monkeypatch.setattr(unbundle, "run_extraction", extract)
    result = unbundle.UnbundleClassifyExtract().process_document(ctx, layout(1))
    assert result.classifications[0].review_outcome == "human_review"
    assert result.fields[0].review_outcome == "human_review"
    assert UNCERTAIN in result.fields[0].validation_messages
    assert result.segments[0].evidence["review_reasons"] == [UNCERTAIN]


def test_unordered_proposals_are_recorded_as_repaired_not_silently_sorted():
    provider = FixedProvider(
        [
            SegmentOut(start_unit=1, end_unit=1, category="w2", confidence=0.9),
            SegmentOut(start_unit=0, end_unit=0, category="w2", confidence=0.9),
        ]
    )
    docs = identify_documents(context(provider), layout(2), ["page"] * 2, DocumentResult())
    assert [(d.start, d.end) for d in docs] == [(0, 0), (1, 1)]
    assert all(REPAIRED in d.review_reasons for d in docs)
    assert all("unordered_proposals" in d.boundary["reasons"] for d in docs)


def test_category_equality_without_continuation_evidence_cannot_merge_pages():
    provider = FixedProvider(
        [SegmentOut(start_unit=0, end_unit=1, category="note", confidence=0.99)]
    )
    docs = identify_documents(context(provider), layout(2), ["page"] * 2, DocumentResult())
    assert [(d.start, d.end) for d in docs] == [(0, 0), (1, 1)]
    assert all("missing_continuation_evidence" in d.boundary["reasons"] for d in docs)


@pytest.mark.parametrize("cited_id,invalid", [("p1:l1", True), ("p1:l10", False)])
def test_source_must_be_an_exact_token_in_supplied_evidence(cited_id, invalid):
    from docai.schemas.layout import Line

    document = layout(1)
    document.pages[0].lines = [
        Line(id="p1:l1", text="Omitted borrower name"),
        Line(id="p1:l10", text="Supplied note title"),
    ]
    provider = FixedProvider(
        [
            SegmentOut(
                start_unit=0,
                end_unit=0,
                category="note",
                confidence=0.99,
                sources=[SourceRef(unit_index=0, ids=[cited_id])],
            ),
        ]
    )
    docs = identify_documents(
        context(provider), document, ["Supplied note title [p1:l10]"], DocumentResult()
    )
    assert ("invalid_source" in docs[0].boundary["reasons"]) is invalid
    assert bool(docs[0].sources) is not invalid
