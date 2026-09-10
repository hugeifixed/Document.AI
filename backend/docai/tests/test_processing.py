"""Layout preservation, chunking, reconciliation, grounding, span mapping,
regex safety, normalization, validation rules, metrics."""
import pytest

from docai.evaluation.metrics import classification_metrics, extraction_metrics, segmentation_metrics
from docai.exceptions import ContextLimitExceeded, UnsafeRegex
from docai.grounding.locate import locate_in_page
from docai.grounding.span_mapping import map_pdfjs_selection, map_word_ids, normalize_pdfjs_rects
from docai.layout.chunk import plan_chunks
from docai.layout.preserve import preserve
from docai.layout.reconcile import reconcile
from docai.schemas.config import ChunkingConfig, LayoutPreservationConfig
from docai.schemas.layout import LayoutDocument, LayoutPage, Line, Span, Table, TableCell, Word
from docai.schemas.llm import FieldOut
from docai.validation.normalize import normalize_value, values_match
from docai.validation.regex_safety import validate_regex
from docai.validation.rules import validate_field


def _page(words_texts, tables=None):
    words, lines, off, x = [], [], 0, 0.1
    for i, t in enumerate(words_texts):
        words.append(Word(id=f"p1:w{i}", text=t, span=Span(offset=off, length=len(t)),
                          polygon=[x, 0.1, x + 0.05, 0.1, x + 0.05, 0.12, x, 0.12]))
        off += len(t) + 1; x += 0.06
    lines.append(Line(id="p1:l0", text=" ".join(words_texts), span=Span(offset=0, length=off - 1),
                      polygon=[0.1, 0.1, x, 0.1, x, 0.12, 0.1, 0.12], word_ids=[w.id for w in words]))
    return LayoutPage(index=0, number=1, width=8.5, height=11, unit="inch", content=" ".join(words_texts),
                      words=words, lines=lines, tables=tables or [])


def test_preserve_renders_tables_as_markdown_with_ids():
    t = Table(id="p1:t0", row_count=2, col_count=2, cells=[
        TableCell(id="p1:t0:r0:c0", row=0, col=0, text="Item", kind="columnHeader"),
        TableCell(id="p1:t0:r0:c1", row=0, col=1, text="Amount", kind="columnHeader"),
        TableCell(id="p1:t0:r1:c0", row=1, col=0, text="Wages"),
        TableCell(id="p1:t0:r1:c1", row=1, col=1, text="1,000.00")])
    page = _page(["Hello", "world"], tables=[t])
    out = preserve(LayoutDocument(document_id="d", source_format="pdf", service="fixture", units=[page]),
                   LayoutPreservationConfig())[0]
    assert "| Item | Amount |" in out and "| Wages | 1,000.00 |" in out and "r1c1=p1:t0:r1:c1" in out
    assert out.startswith("=== PAGE 1")


def test_chunking_strategies_and_explicit_fallback():
    units = ["a" * 5000, "b" * 5000, "c" * 5000]
    assert len(plan_chunks(units, ChunkingConfig(strategy="page")).chunks) == 3
    p = plan_chunks(units, ChunkingConfig(strategy="whole_document", whole_document_max_chars=10000, fallback="context_length",
                                          chunk_chars=6000, overlap_chars=500))
    assert p.strategy_used == "context_length" and p.fallback_used and p.chunks[1].continuation
    with pytest.raises(ContextLimitExceeded):
        plan_chunks(units, ChunkingConfig(strategy="whole_document", whole_document_max_chars=10000, fallback=None))


def test_reconciliation_policies_keep_conflicts():
    a = [FieldOut(name="x", value="1", confidence=0.6)]
    b = [FieldOut(name="x", value="2", confidence=0.9)]
    c = [FieldOut(name="x", value="1", confidence=0.7)]
    r = reconcile([a, b, c], "highest_score")["x"]
    assert r.field.value == "2" and r.conflict and len(r.candidates) == 3
    assert reconcile([a, b, c], "majority")["x"].field.value == "1"
    assert reconcile([a, b, c], "first_non_null")["x"].field.value == "1"
    assert reconcile([a, b, c], "conflicts_to_review")["x"].field.confidence == 0.0


def test_grounding_exact_digits_fuzzy():
    page = _page(["SSN:", "766-16-2186", "Name", "Maria", "Alvarez"])
    assert locate_in_page("766-16-2186", page)["method"] == "exact"
    assert locate_in_page("766162186", page)["method"] == "exact"      # exact-after-normalization
    assert locate_in_page("766 16 2186", page)["method"] == "digits"   # split tokens → digit stream
    hit = locate_in_page("Maria Alvarez", page)
    assert hit["method"] == "exact" and hit["word_ids"] == ["p1:w3", "p1:w4"] and len(hit["polygon"]) == 8
    assert locate_in_page("Mario Alvarez", page)["method"] == "fuzzy"
    assert locate_in_page("nothing here", page) is None


def test_pdfjs_span_mapping_and_word_boxes():
    page = _page(["Total", "1,234.56", "Total", "9.99"])
    rects = normalize_pdfjs_rects([{"x": 0.16 * 612, "y": 792 * (1 - 0.12), "width": 0.05 * 612, "height": 0.02 * 792}], 612, 792)
    m = map_pdfjs_selection(page, "1,234.56", rects)
    assert m["word_ids"] == ["p1:w1"] and m["score"] >= 0.9
    # repeated text: geometry disambiguates the second "Total"
    rects2 = normalize_pdfjs_rects([{"x": 0.22 * 612, "y": 792 * (1 - 0.12), "width": 0.05 * 612, "height": 0.02 * 792}], 612, 792)
    m2 = map_pdfjs_selection(page, "Total", rects2)
    assert "p1:w2" in m2["word_ids"]
    wb = map_word_ids(page, ["p1:w3"])
    assert wb["text"] == "9.99" and wb["method"] == "word_boxes"


def test_regex_safety():
    validate_regex(r"^\d{3}-\d{2}-\d{4}$")
    for bad in [r"(a+)+$", r"(\w+)\1", r"a**", "(" * 25 + ")" * 25, "x" * 500]:
        with pytest.raises(UnsafeRegex):
            validate_regex(bad)


def test_normalization_and_matching():
    assert normalize_value("$76,031.65", "currency") == "76031.65"
    assert normalize_value("March 4, 2026", "date") == "2026-03-04"
    assert normalize_value("766-16-2186", "identifier") == "766162186"
    assert values_match("76,031.65", "76031.65", "currency")
    assert values_match("100.00", "100.90", "currency") and not values_match("100.00", "102.00", "currency")
    assert values_match("03/04/26", "2026-03-04", "date")
    assert values_match("Maria Alvarez", "Maria  Alvarez", "string", "fuzzy")
    assert not values_match("", "x", "string")


def test_validation_rules_never_mutate():
    rules = [{"kind": "regex", "pattern": r"^\d{3}-\d{2}-\d{4}$"}, {"kind": "suggest_normalized"}]
    out = validate_field("ssn", "766 16 2186", rules, {}, "identifier")
    assert out.status == "failed" and out.suggested_correction == "766162186"
    cross = validate_field("fed", "50000", [{"kind": "cross_field", "expr": "wages >= fed"}], {"wages": "40000", "fed": "50000"}, "currency")
    assert cross.status == "failed"
    assert validate_field("x", None, [{"kind": "required"}], {}).status == "failed"
    assert validate_field("x", "5", [{"kind": "range", "min": 1, "max": 10}], {}).status == "passed"


def test_metrics_taxonomy_hand_checked():
    rows = [{"field": "f", "truth": "1", "pred": "1"}, {"field": "f", "truth": "", "pred": ""},
            {"field": "f", "truth": "", "pred": "9"}, {"field": "f", "truth": "1", "pred": ""}]
    m = extraction_metrics(rows, {"f": {"type": "string"}})["per_field"]["f"]
    assert (m["match"], m["true_blank"], m["spurious"], m["missing"]) == (1, 1, 1, 1)
    assert m["precision"] == m["recall"] == m["specificity"] == m["npv"] == 0.5 and m["accuracy"] == 0.5
    c = classification_metrics([("a", "a"), ("a", "b"), ("b", "b"), ("b", "other")])
    assert c["accuracy"] == 0.5 and c["other_or_unclassified_rate"] == 0.25 and c["matrix"][0][0] == 1
    s = segmentation_metrics([{"start": 0, "end": 0, "category": "x"}, {"start": 1, "end": 2, "category": "y"}],
                             [{"start": 0, "end": 0, "category": "x"}, {"start": 1, "end": 2, "category": "y"}], 3)
    assert s["boundary_f1"] == 1.0 and s["exact_segment_match"] and s["page_level_category_accuracy"] == 1.0
