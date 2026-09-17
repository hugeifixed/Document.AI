# Reliable processing of mixed document bundles

Status: Proposed; implementation has not started.

Type: Backend correctness and resilience, with focused workflow-builder and review UX changes.

## Problem and outcome

A single uploaded PDF can contain many separate W-2s, 1099s, and multi-page promissory notes.
Identifying the category of a page is not sufficient: two adjacent W-2s must remain separate
document instances, while continuation pages of one note must stay together. Incorrect grouping
can cause extraction reconciliation to select values from different documents as though they
belonged to one record.

Deliver a bounded, reviewable processing path that preserves document identity and page evidence,
reports uncertain boundaries honestly, and can recover completed work after interruption.
The existing Django services, adapters, task runners, workflow snapshots, and result/review models
remain the foundation. Do not introduce a second orchestration platform.

Success means measured correctness on representative bundles, not a guarantee that every
model-proposed classification is correct. OCR coverage, grouping completeness, extraction
completion, and human approval must remain distinct concepts.

## Verified current behavior

- `backend/docai/workflows/unbundle.py` sends one segmentation request containing the first
  500 normalized characters from each included page. `segmentation_strategy` is declared in
  configuration but does not control that request.
- `validate_segments()` repairs gaps and overlaps while retaining proposed confidence/category;
  successful repairs do not currently produce a dedicated uncertainty signal.
- Extraction chunking happens within each proposed segment. Whole document therefore means the
  identified document in this workflow, not necessarily the uploaded file.
- `backend/docai/layout/reconcile.py` selects one candidate per field name within a segment.
  It does not recover separate document instances from an incorrectly merged segment, or
  generically concatenate list entries across chunks.
- The DI retry wrapper covers submission and polling together. Extraction results are persisted
  after the workflow returns; there are no durable completed-chunk extraction checkpoints.
- Each segment rebuilds preserved text for the full layout. Reading one page's layout loads and
  validates the complete layout artifact.

## Scope and delivery sequence

Keep this as one tracked specification with independently reviewable implementation slices.
Do not present the entire work as a small UI-only change.

| Slice | Deliverable | Required before |
| --- | --- | --- |
| B1 | Honest boundary validation and explicit document-instance semantics | Trusting mixed-bundle results |
| B2 | Bounded segmentation, reconciled window boundaries, effective configuration | Representative 600-page classification test |
| B3 | Extraction chunk correctness, list-conflict handling, workflow UI clarity | Trusting extracted results from long documents |
| B4 | OCR operation recovery and durable extraction checkpoints | Interruption/recovery qualification |
| B5 | Remove repeated full-document work; operational preflight and benchmark | Large-document performance qualification |

B1–B3 establish correctness. B4–B5 establish resilience and usable performance. A smaller
observational baseline may run earlier, with these limitations recorded.

## B1 — Document identity and honest boundaries

1. Retain a distinct document instance for every detected business document, even when adjacent
   instances share a category. Use existing segment identity where possible; avoid a parallel
   model of the same business concept. All fields and classifications retain that identity.
2. Use evidence of document starts and continuations: form identifiers, titles, page numbering,
   relevant entity/loan identifiers, and configured continuation characteristics. A matching
   category alone is insufficient evidence to merge pages. Missing or noisy identifiers must
   remain uncertain rather than forcing a split or merge.
3. Separate raw proposals from validated boundaries. Deterministic structural checks detect
   gaps, overlaps, out-of-range pages, invalid continuation references, and excluded pages.
4. Never silently assign an uncovered page to a confident neighboring document. Preserve an
   explicit unresolved range, or record a provisional assignment with a review requirement.
   Do not invent a replacement confidence score as if it came from the model.
5. Boundary corrections retain the proposed and effective ranges, reason codes, and provenance.
   Add proposed machine-readable review reasons `SEGMENTATION_BOUNDARY_UNCERTAIN` and
   `SEGMENTATION_BOUNDARY_REPAIRED` to the existing warning/review contract. These are review
   conditions, not retryable provider errors. Final naming must follow existing code conventions.
6. Every original page is accounted for as assigned, unresolved, or explicitly excluded under
   the existing blank-page policy. Preserve original page numbers and evidence coordinates.
   Page coverage alone must not mark classification or review complete.
7. Continue extracting unambiguous instances. Clearly mark affected provisional results and
   prevent existing delivery/readiness cues from describing unresolved boundaries as approved.

The first iteration supports contiguous document instances at page boundaries. Multiple forms
on one physical page and interleaved/noncontiguous documents are outside automatic grouping
scope; detect/flag ambiguity where possible and document the limitation. Do not imply that a
`continuation_of` reference alone implements reliable noncontiguous extraction.

## B2 — Bounded segmentation

1. Replace the single all-pages segmentation request with ordered, bounded page windows and
   overlap. Enforce an input budget including instructions, category descriptions, source IDs,
   and page evidence, while reserving output capacity. A character limit is a guardrail, not a
   claim to measure tokens exactly. Make actual budget assumptions explicit and testable.
2. Build compact page evidence that can include distinguishing content beyond the first 500
   characters. Preserve source references. Bound dense single-page input explicitly; report
   insufficient evidence instead of silently treating truncated context as a complete page.
3. Reconcile overlapping windows before finalizing instances. A note crossing a window boundary
   remains one instance when evidence supports continuation; two consecutive W-2s remain two
   instances. Resolve disagreement with a bounded boundary-specific attempt, then route residual
   uncertainty to review. No unlimited model loop or whole-bundle fallback request.
4. Give segmentation its own validated configuration, distinct from extraction chunking.
   Replace or explicitly retire the ineffective `segmentation_strategy` field. Unsupported
   settings must not validate successfully and then be ignored. Update examples and seeded
   defaults together; no historical-data repair project is required.
5. Snapshot effective settings, prompt versions, window ranges, and boundary decisions with the
   run. Record segmentation token usage and progress through existing instrumentation without
   placing document text or identifiers into general logs.
6. Keep the algorithm in a cohesive workflow/domain module with typed inputs and outputs.
   Providers perform model calls; they do not own persistence, UI policy, or ORM queries.

## B3 — Extraction semantics and UI

### Backend

- Extract and reconcile only within an established document instance. Preserve instance, page,
  chunk, and source provenance through persistence, review, exports, and headless results.
- Preserve text once per layout/configuration and reuse it across segments.
- Retain the current whole-document threshold and explicit fallback behavior, but validate
  unsupported/ineffective combinations. Fallback applies when that threshold is exceeded;
  it is not a generic retry for truncation, invalid output, or networking failures.
- Bound oversized section blocks in section-aware chunking; heading/paragraph detection must
  not bypass the request budget. Account for overlap, source markers, and prompt overhead.
- When list-valued fields have differing candidates across chunks, retain candidates and require
  review instead of silently treating the highest-confidence list as complete. Generic list
  concatenation is out of scope: overlapping windows and legitimate repeated rows make it unsafe
  without row-level provenance. Scalar conflicts continue using the explicit reconciliation policy.
- Invalid/truncated extraction output remains visibly incomplete. A successful call or processed
  chunk count is not proof that every configured field was found.

### Workflow builder and results

- Rename the group to **Extraction chunking**. For unbundling, explain: “Controls how each
  identified document is divided for extraction. It does not determine where documents begin
  or end.” Other workflow types receive wording matching their actual processing boundary.
- For unbundling, label the whole-document choice **Whole identified document** while retaining
  the internal value. Describe section-aware as grouping by headings and paragraphs; avoid
  implying it performs model-based semantic document identification.
- Show chunk size and overlap only when a selected strategy or fallback uses them. Show the
  whole-document threshold and fallback only when applicable. Preserve power-user JSON editing
  and round-trip equivalence with the form; do not silently discard valid advanced settings.
- Explain that sizes are characters and output tokens are a separate model setting. Disable
  or explain choices irrelevant to the selected document/workflow context.
- Show identified documents using category plus page range and a stable instance number, e.g.
  “W-2 · Document 2 · Page 2” and “Promissory note · Document 3 · Pages 3–18”. Make repeated
  categories distinguishable without exposing sensitive identifiers in display titles.
- Show grouping uncertainty at the document/segment level with an actionable review link and
  a compact details disclosure. If boundary editing is not supported, explain that a corrected
  workflow/reprocessing is needed; accepting an extracted field must not approve the boundary.
- Reuse current design tokens, components, polling, and review flows. Keep keyboard operation,
  focus behavior, WCAG 2.2 requirements, both themes, and narrow layouts intact. No new dashboard.

## B4 — Recovery and idempotency

- Separate DI submission from polling. Persist the provider operation reference promptly and
  poll the same operation on a recoverable polling failure. Keep operation details protected
  and validate them before reuse; never expose credentials or arbitrary fetch URLs.
- Bind reusable operations/artifacts to source identity and effective analysis configuration.
  Resume only when those match. If an operation is unavailable/expired, make resubmission an
  explicit, recorded decision with a bounded retry budget.
- A crash after provider acceptance but before recording its reference is an ambiguous outcome.
  Document that residual duplicate-submission risk; do not promise exactly-once external billing.
- Store validated completed extraction-chunk outputs durably, keyed by run item, stable segment,
  chunk/input identity, and effective configuration/prompt version. Resume only compatible work.
  Reuse existing artifact/storage boundaries and avoid full sensitive outputs in ordinary logs.
- Protect checkpoint publication and final persistence against duplicate deliveries and stale
  worker claims. Recovered work cannot duplicate fields, classifications, or recorded usage events.
  Real repeated provider calls still count as separate usage; checkpoint reuse creates no fake call.
- Preserve cancellation and terminal states. A stale worker cannot publish after cancellation or
  overwrite a newer attempt. Thread/sync execution and Celery use the same domain recovery rules.
- Keep Oracle and SQLite compatible: scalar indexed identities/constraints, no JSON/NCLOB
  grouping or equality requirements. No long database transaction across network calls.

## B5 — Performance and operational readiness

- Make per-page layout retrieval avoid reading/validating the entire artifact on every request.
  Select the smallest storage/service change supported by measurement; do not require Redis or
  an unbounded process cache. Retain run-specific layout isolation and storage-agnostic access.
- Measure peak worker memory, artifact size, stage duration, provider calls/tokens, repeated work,
  and page-view latency. Include original bytes, rendered scans, and normalized layout in memory
  analysis. Do not assume that raising the upload/page limit makes processing safe.
- Document effective upload/page limits, service tier, task time limits, retry budgets, broker
  visibility/redelivery settings, temporary/shared disk capacity, and supported worker pool.
  Distinguish network timeouts from the overall job deadline and supported pool enforcement.
- Keep a single-file baseline separate from concurrency testing. A worker concurrency of ten
  does not divide one file into ten parallel tasks. Per-segment distributed fan-out is deferred
  until measurements establish a need; checkpoints do not require that architectural change.

## Acceptance scenarios

Use synthetic or approved fixtures with an independently recorded page-to-document manifest.
Automated tests use deterministic provider responses, including deliberately bad proposals.

| Scenario | Required behavior |
| --- | --- |
| Two adjacent W-2s with different identities | Two instances and independent field sets; no cross-instance reconciliation |
| Several copies of the same W-2 | Separate source instances; no implicit business deduplication |
| Long note crossing segmentation windows | One instance when continuation evidence agrees; otherwise explicit uncertainty |
| W-2 → note → 1099 → another note | Correct ordered ranges, categories, extraction schemas, and source page references |
| Gaps, overlaps, invalid ranges/references | Recorded structural issues; no silently trusted repair or lost page |
| Mixed digital/scanned pages and excluded blanks | Original numbering preserved; every page accounted for |
| Dense page or oversized heading-free section | Request budget respected or actionable incomplete/review outcome |
| Different list candidates across extraction chunks | All candidates retained and review required; no invented complete combined list |
| DI transient polling failure | Existing operation polled again; no new submission while a valid operation is known |
| Worker stops after successful chunks | Resume compatible checkpoints; completed chunks not called again |
| Duplicate delivery or cancelled/stale attempt | No duplicate final results or stale publication |
| Repeated page navigation in a large layout | No full-artifact parse per request; run isolation and authorization preserved |
| Form ↔ JSON configuration editing | Equivalent validated settings; controls describe actual execution |

## Verification and rollout

1. Add focused unit/service/API tests for boundary decisions, budgets, checkpoints, isolation,
   review flags, and provider submission counts. Keep live Azure calls outside automated CI.
2. Update OpenAPI/TypeScript contracts, workflow examples, seed defaults, architecture, and known
   limitations where behavior changes. Review downstream review counts, readiness cues, metrics,
   exports, and headless polling/results so uncertainty is consistent across entry points.
3. Run `python scripts/verify.py` and the optional browser suite for UI interactions. Exercise
   keyboard behavior, both themes, and supported viewports. Retain existing coverage gates.
4. Manually qualify approved digital, scanned, and mixed bundles at 50, 200, then 600 pages;
   separately exercise interrupted processing in a controlled environment. Record exact workflow,
   deployment/tier, machine resources, expected manifest, errors, timing, memory, tokens, and review
   outcomes. Do not automatically launch paid provider runs as part of implementing this ticket.
5. Deterministic fixtures must meet their exact expected ranges/results. For live-model testing,
   agree dataset-specific accuracy and latency thresholds before execution, publish measured
   errors, and require every input page to be accounted for. No unsupported enterprise-ready claim.

Out of scope: replacing DI/LLM providers, adding SSO/MCP/webhooks, project authorization redesign,
new brokers, distributed segment orchestration, historical data repair, automatic deduplication
of repeated forms, and a general-purpose visual boundary editor.
