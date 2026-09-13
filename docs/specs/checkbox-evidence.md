# Checkbox evidence and presentation

## Problem and scope

Default generic extraction can expose generated `[checkbox p1:sm2: unselected]` markers as fields.
The saved Azure layout has selection-mark IDs, states and polygons, but grounding only searches text.
This creates high-confidence fields with no source spans and unnecessary review. Implement a focused
fix in the existing grounding and field-presentation boundaries, not a separate extraction framework.

## Acceptance criteria

1. Ground a field against exactly one identifiable selection mark in the saved layout. Prefer explicit
   source citations. Support an exact canonical marker in the field name/evidence when explicit mark
   citations are absent, so existing prompt versions can produce grounded results on new runs.
2. Verify the original page/unit, allowed chunk/segment indexes, exclusion policy, selection state and
   a finite, normalized, non-degenerate polygon. The field's selected/unselected state must match the
   referenced mark. Handle casing/outer whitespace only; do not infer yes/no semantics from a label.
3. Unknown IDs, wrong pages, contradictory references/states, ambiguous multiple marks, malformed
   geometry or excluded pages remain ungrounded (or follow existing invalid-source rejection).
   Once a field claims checkbox evidence, failed verification must not fall back to a coincidental
   text occurrence or an unrelated mark. Genuine text and spreadsheet grounding remain unchanged.
4. Persist the verified original unit, polygon and stable mark ID through the existing SourceSpan
   contract (`word_ids` is the existing stable layout-ID carrier), using mapping method `selection_mark`.
   Preserve field names, raw values, exports, model scores and existing review/routing rules. Mapping
   certainty is distinct from provider/model confidence. No database migration is expected.
5. In the UI, preserve business names already supplied by a schema/model. Render a raw canonical name
   such as `checkbox p1:sm2` as `Checkbox 3 · Page 1`, and show `Checked`/`Unchecked` for the selection
   state where it is identifiable as checkbox data. Keep underlying identifiers and values intact.
   Share presentation logic where the same field appears in review/results/queue and evidence actions.
   Do not guess nearby labels or invent semantics. Custom schemas already provide governed names;
   document that option without changing users' workflow configurations or stored prompt versions.
6. Checkbox evidence copy must distinguish a verified checkbox location from unverified evidence.
   Do not present the generated marker as a literal quote from the document. Clarify that displayed
   confidence is the model's confidence, independent of source verification, without adding a banner.
   Keep keyboard focus, evidence navigation, clear-selection behavior, light/dark styling, RBAC and
   existing masking intact. Follow frontend/DESIGN.md and cover its four viewport sizes.
7. Verify through synthetic layout/provider fixtures and real service/API persistence tests: both
   checked and unchecked values, explicit and canonical citations, repeated states across pages,
   mismatches, missing/bad geometry, scope exclusions, review routing, geometry serialization and
   promotion/selection consumers where affected. Browser coverage exercises checkbox selection and
   its saved bounding box in both themes. Existing PDF/text/spreadsheet tests must continue passing.
8. No historical repair, reprocessing of live documents, paid provider requests, new dependency, or
   automatic workflow/schema changes. Existing results change only through normal new runs; display
   improvements can apply to old raw names without claiming their evidence is verified.

## Task graph

| Ticket | Deliverable | Dependencies |
| --- | --- | --- |
| CB-1 | Backend checkbox grounding, persistence/regression tests and architecture notes | none |
| CB-2 | Shared readable field presentation, confidence/evidence copy, UI tests and DESIGN notes | none |
| CB-3 | Integrate, verify API/UI agreement, browser/whole-repo checks, two-axis review and fixes | CB-1, CB-2 |

Each implementer works on an isolated branch/worktree. Merge onto one PR branch. The PR links this
specification; no remote issue numbers were supplied, so no closing references are invented.
