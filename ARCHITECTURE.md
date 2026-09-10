# Architecture & design decisions

This document records the decisions the platform is built on, in the order the specification asked for
them to be explained. Where the specification contained a contradiction or an underspecified requirement,
the resolution is stated explicitly rather than silently chosen.

## 1. Package and module structure

```
backend/
  config/            Django project: settings/{base,local,production,test}.py, urls, celery (optional), wsgi
  docai/             the reusable sub-application
    models/          catalog (projects, datasets, versioned configs), documents/artifacts/units,
                     results (runs, segments, classifications, fields, spans, evaluations), labeling/audit
    schemas/         Pydantic: normalized layout, every LLM request/response, per-workflow config schemas
    adapters/        ONLY place vendor SDKs are imported
      azure_identity.py            DefaultAzureCredential, token provider, retries, error sanitization
      layout/{azure_di,pypdf_text,excel,plain_text,fixture}.py   LayoutProvider implementations
      llm/{azure_openai,mock}.py   StructuredLLM implementations (LangChain + Pydantic / deterministic mock)
      storage.py                   Django storage wrapper with Windows-safe naming
    layout/          preserve.py (non-LLM layout preservation), chunk.py, reconcile.py
    grounding/       locate.py (value → words/polygon), span_mapping.py (PDF.js ↔ layout reconciliation)
    validation/      regex_safety.py, normalize.py, rules.py
    evaluation/      metrics.py (extraction taxonomy, classification, segmentation, quality indicators)
    workflows/       strategy registry + six strategies + shared extraction core + review routing + prompts
    services/        business logic: ingestion, layouts, governance, runs, review, labeling, evaluation, export, dashboard, audit
    repositories/    query helpers (select_related/prefetch) used by viewsets
    tasks/           runner abstraction (sync/thread/celery) + Celery shims
    api/             session login/logout, envelope renderer, exception handler, pagination, permissions, filters, v1 viewsets/routers
    serializers/     DRF serializers (with role-based masking of sensitive content)
    logging/         loguru sinks, Django interception, correlation context, sanitization, request timing
    synthetic/       hand-rolled PDF writer + synthetic document generators (test data only)
    management/      seed_defaults, make_synthetic_data, run_sample
    tests/           pytest-django tests, including session authentication and CSRF enforcement
frontend/src/
  api/ (client + types) · auth/ (session provider + route guard) · store/ (zustand prefs) · hooks/ (URL table state) · a11y/ (live region)
  components/ (DataTable, ErrorNotice, ConfirmDialog, UploadDropzone, ProductTour, ui) · layouts/AppShell · pages/ (login + platform routes)
```

The frontend checks `/api/v1/auth/session/` before mounting protected pages. `/login` uses CSRF-protected
session login/logout endpoints shared with Django admin. Authentication failures return users to sign-in
with a local return URL; permission errors remain on the requested page. Logout and expiry clear the
client query cache and selected project/dataset. The server session is invalidated on logout.
The sign-in form uses the existing React Hook Form/Zod validation and shared Axios client; its DRF
serializer lives in `serializers/`, and the API delegates authentication to Django's built-in session APIs.
No additional authentication package is required.

Layering rule, enforced by structure: **views → services → (workflows, adapters, repositories)**. Views validate and
authorize; services own transactions and business rules; workflows are pure functions over normalized layouts that
return dataclasses; adapters are the only modules that import Azure/LangChain/pypdf/openpyxl.

Frontend UI follows daisyUI 5 with Tailwind CSS 4:

* `frontend/src/app.css` defines the two custom themes with CSS plugins. Components use semantic colors;
  theme values are not duplicated in a separate dark-mode palette. Sonner follows the same theme.
* Use current `fieldset`/`label`, `input`, `select`, and `textarea` classes, with explicit control widths
  and responsive grids. Labels use `htmlFor`/`id`; help and validation messages use `aria-describedby`.
  Removed v4 classes such as `form-control`, `label-text`, and `input-bordered` must not be reintroduced.
* Shared cards and statistics use `card`/`card-body` and `stats`/`stat`. Navigation uses `menu` lists,
  `menu-active`, visible text, and decorative Heroicons. Mobile navigation includes context selectors.
* Modals use native `<dialog>.showModal()` and `method="dialog"` close forms for keyboard focus trapping,
  Escape, and focus restoration. Shared `ScrollRegion` keeps overflowing data keyboard-scrollable.
* Custom CSS is reserved for accessibility behavior and document overlays. React Hook Form, Zod,
  TanStack Query/Table, Zustand, Axios, and Sonner retain their existing responsibilities.

Reference: [daisyUI 5 migration guidance](https://daisyui.com/docs/upgrade/).

Motion uses CSS only: 120 ms control feedback and 180 ms panels/toasts, with a 1% dialog scale and
12 px sidebar entrance. Focus outlines appear immediately. `prefers-reduced-motion: reduce` disables
animations/transitions and button movement; native dialog focus and status announcements remain active.
Table/dashboard skeletons are static. `AsyncButton` reserves both label widths, prevents duplicate
activation while pending, and announces progress through the existing polite live region. Color pairs
in error-banner actions change together to preserve contrast throughout hover feedback.

Typography keeps the existing sans/monospace font stacks and uses local system fallbacks without web-font
downloads. Tailwind theme roles in `app.css` define page titles (24 px), section titles (18 px), and captions
(13 px) in rem units; card titles remain 16 px and compact body/form text 14 px. Headings wrap naturally,
and `reading-copy` limits explanatory prose to 65ch with 1.6 line height. JSON editing uses 14 px monospace.
Table headers use the contrast-tested secondary color. Quantitative TanStack columns opt into
`meta: { numeric: true }` for end alignment and lining/tabular figures; timestamps also use tabular figures.
Buttons, badges, and the top bar can grow with text, and sidebar dimensions scale with the root font size.
Check 200% text enlargement, 320 CSS px reflow, and [WCAG text-spacing overrides](https://www.w3.org/WAI/WCAG22/Understanding/text-spacing.html)
when changing these shared styles; dense tables retain their own scrolling region.

Frontend information architecture follows the document-processing lifecycle while preserving all existing URLs:
`Workspace` (dashboard, projects, datasets/documents), `Configure` (workflow versions and creation), `Process`
(runs and extracted results), `Review` (human review and ground truth), and `Measure & share` (evaluations and
exports). Account settings, staff admin, API documentation, and logout are consolidated in the header account menu.
Project and dataset selectors are labeled
as the current working context. Deep run, review, labeling, and workflow-creation screens use hierarchy-based
breadcrumbs; dashboard workload cards link to their canonical destinations. Navigation labels and page titles use
the same vocabulary. Task-only destinations and write controls follow the roles already returned by the session API:
operators configure and run, reviewers review and label, and approvers approve or promote. Read-only history and
results remain visible to authenticated platform roles, and backend permissions remain authoritative.
List search is scoped and labeled on projects, documents, workflow versions, runs, extracted results, review items,
and ground-truth documents. It uses each existing DRF search endpoint and the shared URL table state, so queries
survive refresh and browser navigation without a separate index or frontend search dependency.
No navigation analytics, search logs, or user-research artifacts are stored in this repository, so this lifecycle
grouping is a reasoned first pass to validate with real task paths as usage evidence becomes available.

Authenticated users receive a short NextStepjs product tour once per browser, username, and tour version. Completing
or dismissing it records only an acknowledgement flag in local storage; the account menu can always start it again.
Desktop and mobile variants target controls that are visible in their respective layouts. The custom daisyUI card
uses semantic theme colors, traps keyboard focus, supports Escape dismissal, and restores the prior focus target.

### Upload lifecycle and large files

The browser keeps selected documents in a reviewable queue and sends one file per request with at most two requests
in flight. Each file therefore has independent progress, cancellation, rejection, and retry state; a failed transfer
does not restart a large batch. React Dropzone provides early type, size, and count feedback, while the API repeats
all validation because browser checks are not a security boundary.

Django keeps files up to `FILE_UPLOAD_MAX_MEMORY_SIZE` in memory and spools larger inputs to its upload temporary
directory. Ingestion consumes that seekable file in bounded chunks for SHA-256, signature and content inspection,
and `default_storage.save()`. It does not create a second whole-file byte copy. The request returns only after the
original is stored and the synchronous safety checks pass. OCR, Azure Document Intelligence, and workflow extraction
do not run during upload; they start when a run processes the validated document. With the Celery runner selected,
that later work is already split into independent per-document tasks.

The configured 100 MB default is a deliberate application limit. If deployments need substantially larger or
cross-region uploads, the next step is a quarantine-container flow: the API issues a short-lived, write-only Azure
Blob SAS; the browser uses resumable block upload; a finalize endpoint records the blob reference; and a worker
validates, hashes, and promotes it before the document becomes eligible for runs. That change avoids holding web
workers during transfer and requires a distinct `validating` lifecycle state; it is not part of the current local
storage implementation.

### Task execution and delivery guarantees

`SyncRunner` and `ThreadRunner` require no broker; both complete before the initiating HTTP request returns, while
the thread runner may process documents concurrently on a database that supports it. `CeleryRunner` is the durable
out-of-process option and publishes one UUID-only message per `RunItem`. It does not use a chord or depend on a
Celery result backend: `Run` and `RunItem` are the result store, and each terminal task attempts finalization under
a database row lock after verifying no item remains queued or running.

The worker claim records the Celery task id, ignores a concurrent duplicate id, and permits the same id to resume
after a late-ack redelivery. Failures classified as retryable use bounded exponential backoff with jitter; permanent
failures remain available for manual retry. Delivery count is bounded separately to stop a document that repeatedly
kills a worker from creating an infinite requeue loop. A partial broker publication leaves the run at
`dispatch_failed`; executing it again publishes unfinished items, while completed and actively claimed items are
not duplicated.

Development on Linux uses `prefork`; native Windows uses `threads` or `solo` and is best-effort because Celery does
not officially support Windows. Initial Linux production may use a persistent local filesystem spool only while the
web and worker processes share one host. A whole worker or host crash can strand an in-flight filesystem message;
`recover_stalled_runs` converts `running` or retry-wait items older than the safe task/retry window into visible,
retryable failures.
Redis or RabbitMQ becomes mandatory for multiple worker hosts or broker HA.

## 2. Workflow routing

`WorkflowConfiguration.workflow_type` selects a strategy from the registry (`docai/workflows/base.py`).
Every strategy implements `process_document(ctx, layout) -> DocumentResult`. The run service builds the context
once per run (validated Pydantic config, resolved prompt versions, the LLM adapter) and calls the strategy once
per document. Adding a workflow type = a Pydantic config model + a strategy class + `@register`.

| type | strategy | notes |
|---|---|---|
| `unbundle_classify_extract` | `UnbundleClassifyExtract` | LLM proposes segments from per-unit snippets → hard validation (ordered, non-overlapping, full coverage; whole-file fallback that can never lose pages) → each segment routed to its category's schema |
| `classify_structured` | `ClassifyStructured` | regex-safety-checked rules with weights, groups, exclusions, thresholds; ambiguity → `needs_review`; optional LLM fallback |
| `classify_unstructured` | `ClassifyUnstructured` | LLM votes per chunk; disagreement flag routes to review |
| `extract_structured` | `ExtractStructured` | non-LLM layout preservation → generic extractor (`default` = all key/value pairs, `custom` = schema) |
| `extract_unstructured` | `ExtractUnstructured` | configurable chunking → reconciliation → validation via the shared core |
| `extract_template` | `ExtractTemplate` | versioned template (schema+prompt+model+guidance+chunking) through the same core |

Review routing (`workflows/routing.py`): first matching configured rule wins; defaults send anything ungrounded,
validation-failed, disagreeing, or segmentation-uncertain to human review, and auto-accept only ≥ 0.8.

## 3. Normalized models

* **Layout** (`schemas/layout.py`): one model for pages *and* worksheets. DI output is normalized losslessly —
  words, lines, paragraphs (with roles), tables with row/col spans and cell kinds, selection marks, sections,
  reading order, page size + unit, API version. Polygons are normalized to 0–1 page fractions so PDF.js (points,
  bottom-left origin) and DI (inches/pixels, top-left) compare without unit gymnastics. Stable ids the LLM cites:
  `p3:w12`, `p3:l4`, `p3:t0:r2:c1`, `s0:B7`.
* **LLM I/O** (`schemas/llm.py`): `SegmentationOut`, `ClassificationOut`, `ExtractionOut`, `GenericKVOut` — each value
  carries evidence + `SourceRef`s. Validation failure raises `InvalidModelOutput`; the item is routed to retry/review,
  never coerced.
* **Results** (models): `Segment`, `ClassificationResult`, `ExtractedField` (raw / normalized / reviewed values kept
  separately), `SourceSpan` (word ids, polygon, offsets, cell range, mapping method + score + exceptions).
  Every row records model deployment, prompt/schema versions, API version, strategy and any fallback.

## 4. Chunking and reconciliation

`layout/chunk.py`: `whole_document | page | sheet | context_length | semantic`. `context_length` packs preserved unit
texts into character budgets with overlap carried as an explicit continuation prefix; `semantic` breaks only at
blank lines / headings / unit boundaries (no embeddings — documented). A `whole_document` overflow uses the configured
fallback and **records it** on every field (`fallback_used`); with no fallback it raises `ContextLimitExceeded`.

`layout/reconcile.py`: per-field policy `first_non_null | highest_score | majority | conflicts_to_review`; losing
candidates are kept, `conflict=True` feeds the disagreement flag into routing.

## 5. PDF.js ↔ Azure span mapping, and Excel

`grounding/span_mapping.py`: a PDF.js selection (page, text, rects in PDF user space) is normalized to page fractions,
then matched against layout words by text (exact-after-normalization → digit stream → fuzzy ≥ 86) with geometry IoU
as tie-breaker for repeated text; the method, score, and exceptions are stored on the label alongside **both** spans.
Pages with no text layer use word-box selection (`map_word_ids`). Spreadsheets store workbook/sheet/cell-range plus the
displayed value and formulas (`services/labeling.py::label_from_cells`). Model predictions are grounded the same way
(`grounding/locate.py`) so overlays in the UI come from stored polygons, not re-computed guesses.

## 6. Azure authentication and adapter isolation

`adapters/azure_identity.py` is the single place credentials exist: one process-wide `DefaultAzureCredential`, a
bearer-token provider for the cognitive-services scope, retry with backoff for throttling/timeouts, no retry for auth
failures, and error sanitization (no endpoints or payloads in messages). DI is called with the credential object;
LangChain's `AzureChatOpenAI` receives `azure_ad_token_provider`. Services never import an SDK; adapters are chosen by
settings (`get_layout_provider()`, `get_llm()`).

## 7. Model swapping

A run snapshot records `model.deployment` and parameters; changing the deployment in a `ModelConfiguration` or
workflow config changes nothing else. `settings.DOCAI["LLM_ADAPTER"]="mock"` overrides any workflow's adapter so a
local/test environment can never reach Azure by accident.

## 8. What is implemented vs. placeholder

Implemented and tested end-to-end (offline): ingestion + safety checks, layout normalization (pypdf text layer,
Excel, plain text, DI normalizer), layout preservation, chunking, reconciliation, all six workflows, grounding,
validation rules, review actions with preserved originals, versioned ground truth, dual-span labeling, metrics
(extraction taxonomy incl. specificity/NPV/hallucination rate, classification macro/micro/weighted + confusion matrix,
segmentation boundary/exact/page-level), quality indicators without GT, exports (JSON/CSV/XLSX), envelope + error
codes + trace ids, RBAC with masking, audit trail, cache invalidation, loguru with sanitization, OpenAPI, unfold admin,
health checks, task runner abstraction (sync/thread/celery), synthetic data, backend and frontend tests, frontend build.

Placeholders / not exercised here: the **Azure DI and Azure OpenAI adapters are written against the SDKs but could
not be executed without credentials**; the `external_reference` validation rule records "not executed"; per-project
membership hook; `ReviewPolicy` rows are stored but routing currently reads rules from the workflow config; bulk-review
"undo window" is reported but not implemented as a timer; frontend keyboard text selection in the PDF.js text layer
depends on browser support.

## 9. Assumptions

* Text-layer PDFs are the local development corpus; scanned PDFs, images and DOCX go to DI.
* A "document" for evaluation is the uploaded file; unbundle runs grade segmentation per file and classification per
  segment (page-range labels).
* Ground-truth field labels for a document apply to the whole file; when a file is unbundled, the first non-blank
  prediction for that field name across segments is compared (documented in `services/evaluation.py`).
* Dataset `split` is advisory: the platform records it and warns when an unapproved configuration runs on
  production data, but does not block engineers from evaluating on `test` — that is a governance decision.

## 10. Resolved contradictions and underspecified areas

| Issue in the specification | Resolution |
|---|---|
| §1 "pypdf is the only PDF library" vs §7 "rasterize pages" — pypdf cannot rasterize | Image normalization is scoped to raster inputs (JPEG/PNG/TIFF) and to DI's native PDF handling; PDF pages are never rasterized locally. `ProcessingArtifact` keeps a `page_map` so any future normalization stays traceable. |
| Architecture diagram shows a single "job" | Runs have per-document `RunItem`s with independent state, attempts, idempotency keys and correlation ids; the run aggregates them. |
| §5.4 "layout preservation" undefined | Implemented as a deterministic, non-LLM renderer over the normalized layout: reading order, tables → markdown with cell-id legend, y-band linking of label/value pairs, stable ids in brackets (`layout/preserve.py`). |
| DI JSON "stored in the database" vs Oracle NCLOB limits | Layout JSON is an immutable storage artifact; `SourceUnit` rows hold dimensions, ids and a search preview only. |
| Reconciliation across chunks undefined | Explicit per-field policy, recorded, with candidates retained. |
| PDF.js selection fails on image-only pages | Word-box selection over DI words (`mode=word_ids`). |
| Celery on Windows | Broker-free `thread`/`sync` is the default. Optional Celery selects `threads` (or `solo`) on Windows and `prefork` on macOS/Linux; `prefork` is rejected on Windows. Its filesystem spool defaults to the short `%LOCALAPPDATA%\DocAI\celery` path and is checked against legacy `MAX_PATH`. |
| Redis optionality | `Run`/`RunItem` are the durable result and completion store, so Celery needs only a broker. Filesystem transport supports development and an initial one-host Linux deployment; Redis or RabbitMQ is required for multiple hosts or broker HA. Switching is configuration-driven. |
| "Next.js" stale reference | Vite + React Router, as the rest of the frontend spec states. |
| Refinement loop must not modify configurations | Nothing auto-edits; new versions are explicit, approvals are audited, runs snapshot + hash what they used. |
