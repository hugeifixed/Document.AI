import type { Span } from "@/common/types/api";
import { checkboxEvidence, fieldDisplayName, fieldDisplayValue } from "@/fieldPresentation";
import { testField } from "@/test/fixtures";

const span: Span = {
  id: "span-checkbox",
  unit_index: 0,
  unit_kind: "page",
  text: "unselected",
  polygon: [0.1, 0.2, 0.12, 0.2, 0.12, 0.22, 0.1, 0.22],
  word_ids: ["p1:sm2"],
  cell_range: "",
  mapping_method: "selection_mark",
  match_score: 1,
  offset_start: null,
  offset_end: null,
};

it("aliases only exact canonical names and keeps business names intact", () => {
  expect(fieldDisplayName(" checkbox p1:sm2 ")).toBe("Checkbox 3 · Page 1");
  expect(fieldDisplayName("CHECKBOX P12:SM0")).toBe("Checkbox 1 · Page 12");
  expect(fieldDisplayName(" [checkbox p2:sm4: unselected] ")).toBe("Checkbox 5 · Page 2");
  for (const name of ["Consent", "checkbox p0:sm2", "checkbox p1:sm2 consent", "checkbox p1:sm-1"])
    expect(fieldDisplayName(name)).toBe(name);
});

it("omits the canonical page only when the evidence announcement supplies its location", () => {
  expect(fieldDisplayName("checkbox p1:sm2", { includePage: false })).toBe("Checkbox 3");
  expect(fieldDisplayName("[checkbox p2:sm4: unselected]", { includePage: false })).toBe("Checkbox 5");
  for (const name of ["Page 1 consent", "Checkbox 3 · Page 1", "checkbox p1:sm2 consent"])
    expect(fieldDisplayName(name, { includePage: false })).toBe(name);
});

it.each(["selected", "unselected"])("formats %s only for checkbox data without mutating stored values", (value) => {
  const expected = value === "selected" ? "Checked" : "Unchecked";
  const field = testField({ name: "checkbox p1:sm2", raw_value: value });
  expect(fieldDisplayValue(field, value)).toBe(expected);
  expect(field.raw_value).toBe(value);
  expect(field.name).toBe("checkbox p1:sm2");
  expect(fieldDisplayValue({ name: "Consent", spans: [span] }, ` ${value.toUpperCase()} `)).toBe(expected);
  expect(fieldDisplayValue({ name: "Consent", source_text: `[checkbox p1:sm2: ${value}]` }, value)).toBe(expected);
  expect(fieldDisplayValue({ name: "Application status" }, value)).toBe(value);
  expect(fieldDisplayValue({ name: `[checkbox p1:sm2: ${value}]` }, value)).toBe(expected);
  for (const other of ["***", "[REDACTED]", "yes", "no", "true", "false", "", null])
    expect(fieldDisplayValue(field, other)).toBe(other);
});

it("uses the saved location independently of model score and never quotes a generated marker", () => {
  const field = testField({
    name: "Consent",
    raw_value: "unselected",
    source_text: "[checkbox p1:sm2: unselected]",
    spans: [span],
    grounded: true,
    score: 0.2,
  });
  expect(checkboxEvidence(field)).toBe("Verified checkbox location · Page 1");
  expect(checkboxEvidence({ ...field, spans: [], grounded: false, score: 1 })).toBe("Checkbox location not verified");
  expect(checkboxEvidence(testField())).toBeNull();
});

it("does not call missing, malformed, mismatched or ambiguous saved geometry verified", () => {
  const field = testField({ name: "checkbox p1:sm2", grounded: true, spans: [span] });
  const invalidSpans = [
    [],
    [span, span],
    [{ ...span, polygon: [] }],
    [{ ...span, unit_index: 1 }],
    [{ ...span, word_ids: ["p1:w2"] }],
    [{ ...span, word_ids: ["p1:sm2", "p1:sm3"] }],
    [{ ...span, mapping_method: "exact" }],
    [{ ...span, unit_kind: "sheet" }],
    [{ ...span, polygon: [0, 0, 0, 0, 0, 0, 0, 0] }],
  ];
  for (const spans of invalidSpans)
    expect(checkboxEvidence({ ...field, spans })).toBe("Checkbox location not verified");
  expect(checkboxEvidence({ ...field, grounded: false })).toBe("Checkbox location not verified");
});
