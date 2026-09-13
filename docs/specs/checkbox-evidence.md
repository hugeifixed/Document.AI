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

## Follow-up: compact usage and mouse panning

Requested during integration; include these document-review quality-of-life improvements in the same PR.

9. The existing operator-only LLM token usage card starts collapsed and shows its title and total
   reported tokens. Opening it reveals the current breakdown; keyboard toggling, visible focus,
   loading/error/unmeasured states and RBAC remain accurate. Background usage refresh must update
   the total without resetting an open card. A different run starts collapsed. No new API request.
10. PDF/image preview supports primary mouse dragging to scroll both axes when content overflows.
    Dragging blank page areas pans; selectable text and word-box/interactive targets retain their
    existing behavior. Use a quiet hint/cursor, without adding a toolbar mode or dependency. Touch,
    trackpad and keyboard scrolling stay native. Release, cancellation, lost capture and changing
    the rendered source/page must end dragging. Panning must not change geometry, evidence selection,
    page, zoom or ground-truth data. Verify at 180% zoom with real browser mouse input and retain
    text/word selection regression checks. Both themes and all four viewport sizes apply.

| Ticket | Deliverable | Dependencies |
| --- | --- | --- |
| CB-4 | Native collapsed usage summary, accurate states and unit/browser checks | CB-3 |
| CB-5 | Mouse panning in the preview with selection-safe behavior and unit/browser checks | CB-3 |
| CB-6 | Integrate follow-ups, update DESIGN.md, review and final validation | CB-4, CB-5 |
