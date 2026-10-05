# Preserve repeated fields in auto extraction

## Problem

Default-mode structured extraction can receive several correctly cited values with the
same printed label, such as borrower and co-borrower dates of birth. It currently keeps
only the first case-insensitive field name, silently losing other records before
persistence and visual evidence rendering. Repeated state, postal code, amount, and
checkbox labels have the same problem.

## Required behavior

- Preserve separate occurrences of the same label at different source positions,
  including identical values, multiple pages/sheets, tables, and selection marks.
- Preserve original names, raw values, confidence, grounding, and citation provenance.
  Do not invent record names or specialize for a particular form or borrower.
- Remove a repeated prediction only when its normalized label, unchanged raw value,
  and trustworthy source occurrence identify the same result. Overlapping chunks and
  alternative citations of one occurrence must not multiply the result.
- Never use name or name-plus-value alone to identify an occurrence. If location or
  evidence validity cannot establish identity, retain the candidate for normal review.
  A valid neighbor must not lend trust or geometry to an invalid candidate.
- Keep different or conflicting values, even when a label repeats. Continue existing
  evidence validation, review routing, and optional bounded citation repair.
- Existing persistence, API field lists, and local label/JPG exports must retain the
  separate occurrences using their existing result IDs and source spans.
- Keep custom-schema extraction behavior unchanged. Introduce no migrations, public
  API/configuration fields, prompt changes, provider calls, or new dependencies.

## Task graph

| Ticket | Deliverable | Depends on |
| --- | --- | --- |
| T1 | Implement conservative source-occurrence deduplication with focused workflow tests; update the former name-only expectation. | — |
| T2 | Add independent end-to-end regressions for repeated labels, same-value distinct locations, overlapping chunks, persistence, and visual labels. Use synthetic content. | — |
| T3 | Document occurrence identity, review behavior, and limits in architecture and extraction-test guidance. | T1 |
| T4 | Merge ticket branches, review against this specification and applicable project guidance, and fix actionable findings. | T1, T2, T3 |
| T5 | Run required repository verification, replay the captured repeated-DOB case, and validate a bounded live auto extraction with repaired citations and JPG output. | T4 |

This task was supplied in conversation without remote issue IDs. The specification and
local tickets are tracked here following `docs/agents/issue-tracker.md`; the PR links to
this file and does not invent issue-closing references.

## Acceptance evidence

Regression tests must exercise the actual default-mode extraction strategy. Cover
distinct values and identical values at different occurrences; case/whitespace label
variants; page/sheet identity; narrow word/line/table/checkbox citations; true overlap
duplicates; missing/invalid/ambiguous references; confidence and review preservation;
and independent persistence and visualization of repeated labels. Confirm that a
captured pair of different dates under one label produces two separate grounded fields.

Live validation is directional evidence on the reported photographed form, not an
exhaustive accuracy score or proof that the model discovers every printed value.
