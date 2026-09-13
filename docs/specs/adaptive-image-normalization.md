# Optional adaptive image normalization

## Scope and source

Implement the user's September 12 plan and accepted review corrections. The upload remains
immutable; enhancement runs in the existing thread/Celery run-item worker before DI. No new
queue, mandatory native dependencies, currency accounting, or image editing in the browser.
Everything is disabled by default. This feature is experimental until a representative RND/QA
corpus demonstrates better extraction/review outcomes against direct DI.

## Behavior

- Workflow configuration: `input_quality: {mode: "off" | "adaptive", skip_blank_pages: false}`.
  Keep `di_analysis: {ocr_high_resolution: false}` independent. Snapshot resolved defaults and
  processor profile (`adaptive-v1`) per run. Existing configurations default to off.
- Deployment gate: `DOCAI_IMAGE_NORMALIZATION_ENABLED=false`. Optional extra
  `image-normalization` contains Pillow, opencv-python-headless and pypdfium2. All distributions
  must be older than seven days. Off mode must work with these dependencies absent, without
  importing them. Validate requested capability before run creation and again in the worker.
- Bypass DOCX, spreadsheets, TXT and clean digital PDF pages. Adaptive JPEG/PNG, multipage TIFF,
  scanned PDFs and mixed PDFs produce a derived PDF only when necessary; preserve digital PDF
  pages as original PDF objects. Original page numbering and every page remain intact.
- Render scanned PDF pages at up to 300 DPI with bounded pixels/dimensions, page-at-a-time memory,
  temporary-file cleanup and cancellation checks. PDFium calls and explicit object cleanup must
  use one process-wide mutex in thread workers (PDFium is not thread-safe across documents).
- Conservative EXIF orientation and color-mode normalization, confident deskew (0.5–8 degrees,
  confidence >=0.9), conditional percentile contrast stretching (5th–95th span <80). Never crop,
  hard-binarize, sharpen or destructively denoise. Keep uncertain content.
- Blank skipping is separately opt-in. Require >=99.95% background pixels and no connected
  foreground component >0.02% page area; additionally retain sparse meaningful foreground.
  Do not claim heuristic confidence is calibrated. Preserve original pages, pass selected
  one-based page ranges to DI, reconstruct empty layout placeholders, and explicitly exclude
  skipped pages from downstream prompts without changing original unit indexes. All-blank
  inputs fail clearly with EMPTY_LAYOUT, never invented successful extraction.
- Resource or enhancement failures fall back to safe original input with structured warnings.
  Fatal errors only when safe continuation is impossible. Failed/fallback output is not a
  successful adaptive cache entry; later retries can attempt enhancement again.

## Immutable representations

- Scalar indexed artifact cache keys, scoped to document/source hash/profile/options/adapter/
  API version/model/features/page selection as applicable. No JSON/NCLOB comparison for cache
  lookup. Unique storage paths and atomic publication; never replace historical units.
- Each RunItem references its exact layout artifact; SourceUnit uniqueness includes layout
  artifact. Preserve existing spans and ground-truth links in migrations and later runs.
- Derived PDF uses existing normalized_image artifact kind with clear PDF format metadata.
  Provenance records profile, operations/decisions by original page, dimensions, source hash,
  elapsed time and bytes. Keep LLMUsageEvent focused on LLM usage.
- Update all unit consumers (results, labeling, review, document serialization, search/counts)
  to avoid ambiguity/duplicate units. Ground-truth geometry is scoped to its representation;
  values can still be evaluated across runs. Never show stale overlays on an original or a
  different run's derived input. Do not treat OCR-generated text as a native PDF text layer.
  Core PDF inspection preserves native selection on verified digital pages even in off mode.
  Absence supersedes current field truth across representations; new geometric truth supersedes
  its representation and global absence, preserving historical geometry and latest semantics.
- Document detail, units and processing-source requests accept `run`; verify that run contains
  the document and apply existing content RBAC. Historical sources remain readable when gate
  is subsequently disabled. No direct public artifact paths.

## Shared implementation contract

Backend processor module: `docai.input_quality` exports:

- `capabilities() -> dict`: shape below.
- `validate_input_quality(config: InputQualityConfig, adapter_key: str) -> None`.
- Context manager `prepare_input(path: Path, *, source_format: str,
  config: InputQualityConfig, check_cancelled: Callable[[], None] | None = None,
  progress: Callable[[int, int], None] | None = None)` yields a `PreparedInput` with
  `path: Path`, `source_format: str`, `selected_pages: str | None`, `summary: dict`,
  `page_details: list[dict]`. The context owns temporary output lifetime.
- Summary: `mode`, `status` (off/bypassed/applied/fallback), `profile`, `pages_examined`,
  `pages_adjusted`, `pages_skipped`, `duration_ms`, `warnings` (code/message/pages/retryable).
  Each page detail has one-based `page`, `status` (adjusted/unchanged/skipped/bypassed/fallback),
  `operations`, `width`, `height`, `unit`,
  `has_text_layer`; include geometric transform/size facts when changed.
- `InputQualityConfig` and `DIAnalysisConfig` live in `docai.schemas.config` and are added to
  BaseWorkflowConfig. Provider analyze accepts optional `pages: str | None = None` and
  `ocr_high_resolution: bool = False`; only Azure uses them.

API contracts for frontend:

- GET `/workflows/capabilities/` returns
  `{image_normalization: {available: boolean, reason: string, profile: "adaptive-v1"},
  di_analysis: {ocr_high_resolution: boolean}}`.
- RunItem gains `layout_artifact: UUID | null` and `input_quality: Summary | {}`. Existing
  `stage`, `error_code`, `error_message`, `retryable` fields retain their meaning.
- GET `/documents/{id}/?run={run}` returns units for that run and
  `processing_source: {url: string, file_format: string, layout_artifact: UUID | null,
  is_original: boolean}` (URL uses the protected processing-source endpoint when derived).
- GET `/documents/{id}/units/{index}/?run={run}` selects exact artifact. GET
  `/documents/{id}/processing-source/?run={run}` streams the exact input used (or original).
- Label capture accepts optional `run` to select representation. Label listing `?run={run}`
  returns only compatible geometric labels (document-level labels can remain visible).
- New errors: NORMALIZATION_UNAVAILABLE, NORMALIZATION_FAILED; warning codes
  NORMALIZATION_FALLBACK and NORMALIZATION_LIMIT_EXCEEDED. Fatal resource failures may use
  NORMALIZATION_LIMIT_EXCEEDED. Warnings never populate succeeded RunItem.error_code.
  Fatal normalization stage is normalization; existing native-worker-loss handling remains applicable.
  INCOMPLETE_LAYOUT is a fatal layout error when DI omits a submitted nonblank page; do not
  synthesize that page's content or continue extraction.

## UI acceptance

- Workflow builder uses existing shared controls and RHF/Zod. Operator-only Scan enhancement
  section, original/adaptive choices, nested blank skipping; separate DI high-resolution option.
  Respect backend availability; no frontend environment gate. Run form shows selected policy
  quietly, read-only. Hide irrelevant processing controls for evaluation workflows.
- Run item running status shows Preparing scans; completed summary e.g. `3 pages adjusted ·
  1 blank page skipped`, compact warning/details disclosure, no new wide table column.
- Viewer defaults to source used for active run and offers View original. Changes of run update
  document/layout/source/cache keys together. Original view suppresses incompatible overlays
  and labeling controls. Derived scanned PDFs use OCR word selection, not PDF text selection.
- Preserve validation semantics at upload. No repeated page banners or standalone menu item.
  Existing error panel recognizes fatal codes automatically. Warnings use amber and text.
- Follow DESIGN.md including both themes, keyboard access, wrapping, narrow/tablet layouts,
  WCAG 2.2 AA, and existing live-status announcements without announcing every poll.

## Task graph and ownership

No remote issue/ticket IDs were supplied. These local tickets are the implementation graph;
the PR references this spec rather than inventing issue-closing references.

| Ticket | Deliverable | Dependencies | Owner |
| --- | --- | --- | --- |
| N1 | Processor, optional packages, settings, schemas, DI options, native tests | Contract above | processor worktree |
| N2 | Versioned artifacts/units, run integration, scoped APIs/labels, chunk skipping, tests | Contract; N1 integration | backend worktree |
| N3 | Workflow/run/review UI, accessible summaries and tests | Contract; N2 integration | frontend worktree |
| N4 | Documentation, integration checks, full backend/frontend tests and browser validation | N1, N2, N3 | PR branch |
| N5 | Independent standards/spec reviews, fix findings, finalize PR | N4 | review/fix worktree |

N1/N2/N3 can start together against the agreed contract. N4/N5 are blocked on integration.
Each implementer owns its listed files; only the merger changes the integration branch when
combining commits. Processor owns `input_quality/`, config/schema/provider changes and its tests.
Backend owns models/migrations/services/API/chunking and related tests. Frontend owns frontend
changes. Root owns this spec and top-level/backend documentation. Coordinate interface changes.

## Verification

Realistic generated synthetic fixtures: skew/contrast JPEG/PNG, multipage TIFF, scanned/mixed/
digital PDF, sparse markings/blanks, limits/fallback/cancellation, dependency-free off mode.
Version/cache isolation, retries, historical spans and labeling, RBAC, API error contracts and
page numbering. Offline Azure response mocks assert pages/features; no live credentials or
network calls in CI. Full frontend lint/unit/build and backend Ruff/mypy/tests/80% branch coverage.
Use existing optional Playwright package for theme/viewport/viewer and workflow behavior checks.
Actual DI quality benchmark needs institutional RND/QA inputs and is a rollout requirement;
do not claim synthetic or mocked tests establish OCR gains. Feature stays off by default.
