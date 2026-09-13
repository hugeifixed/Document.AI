import type { ExtractedField, Span } from "@/api/types";
import { polygonBounds } from "@/components/review/evidence";

type PresentableField = { name: string; source_text?: string; spans?: Span[] };
const canonicalName = /^checkbox p([1-9]\d*):sm(0|[1-9]\d*)$/i;
const canonicalMarker = /\[checkbox p([1-9]\d*):sm(0|[1-9]\d*): (?:selected|unselected)\]/i;

/** Display aliases only: callers retain the original field name for edits and API requests. */
export function fieldDisplayName(name: string): string {
  const trimmed = name.trim();
  const marker = canonicalMarker.exec(trimmed);
  const match = canonicalName.exec(trimmed) ?? (marker?.[0] === trimmed ? marker : null);
  if (!match) return name;
  const page = Number(match[1]);
  const index = Number(match[2]);
  if (!Number.isSafeInteger(page) || !Number.isSafeInteger(index + 1)) return name;
  return `Checkbox ${(index + 1).toLocaleString()} · Page ${page.toLocaleString()}`;
}

export function isCheckboxField(field: PresentableField): boolean {
  return (
    canonicalName.test(field.name.trim()) ||
    canonicalMarker.test(field.name) ||
    canonicalMarker.test(field.source_text ?? "") ||
    !!field.spans?.some((span) => span.mapping_method === "selection_mark")
  );
}

/** Only explicit selection states get aliases; business values and masked values stay intact. */
export function fieldDisplayValue(field: PresentableField, value: string | null): string | null {
  if (!isCheckboxField(field) || value == null) return value;
  const state = value.trim().toLowerCase();
  return state === "selected" ? "Checked" : state === "unselected" ? "Unchecked" : value;
}

/** A generated marker is a citation, never a literal quote from the document. */
export function checkboxEvidence(field: ExtractedField): string | null {
  if (!isCheckboxField(field)) return null;
  const span = field.spans.length === 1 ? field.spans[0] : undefined;
  const mark = span?.word_ids.length === 1 ? /^p([1-9]\d*):sm(?:0|[1-9]\d*)$/.exec(span.word_ids[0]) : null;
  if (
    field.grounded &&
    span?.mapping_method === "selection_mark" &&
    span.unit_kind === "page" &&
    mark &&
    Number(mark[1]) === span.unit_index + 1 &&
    polygonBounds(span.polygon)
  )
    return `Verified checkbox location · Page ${(span.unit_index + 1).toLocaleString()}`;
  return "Checkbox location not verified";
}
