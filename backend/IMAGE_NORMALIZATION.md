# Optional scan enhancement

Scan enhancement prepares poor scans for Azure Document Intelligence before layout analysis. It is
off by default and runs inside the existing document-processing worker. Uploading still validates
and stores the immutable original. This is not a second OCR engine.

Drain or stop the old workers before upgrading; do not run old and new layout writers together.
Apply database migrations before starting the updated web server and workers, even when this
feature is off (`.venv/bin/python manage.py migrate`, or `.venv\Scripts\python.exe manage.py migrate`
on Windows). The representation migration preserves existing units, spans and labels; historical
run references are backfilled only when the source layout can be identified unambiguously.

## Enable or disable

From `backend/`, install the optional extra in the web and worker environments:

```bash
uv pip install --python .venv/bin/python -e ".[image-normalization]"
# Include the Celery extra if this environment uses Celery:
uv pip install --python .venv/bin/python -e ".[image-normalization,celery]"
```

Windows PowerShell:

```powershell
uv pip install --python .venv\Scripts\python.exe -e ".[image-normalization,celery]"
```

Pillow, headless OpenCV, NumPy and pypdfium2 are optional and pinned under the seven-day admission policy.
The pre-commit bootstrap installs dev tooling without forcing optional extras into institutional
environments. Install this extra explicitly when verifying the native processing tests.
Set the following on both the web process and workers, and restart both:

```dotenv
DOCAI_LAYOUT_ADAPTER=azure_di
DOCAI_IMAGE_NORMALIZATION_ENABLED=true
```

Configure the Azure DI endpoint and credentials as described in the root README. Select **Improve
scanned pages** in the workflow builder. Enabling the deployment gate does not change existing
workflows; each workflow must opt in. The relevant configuration alongside its other fields is:

```json
{
  "input_quality": {"mode": "adaptive", "skip_blank_pages": false},
  "di_analysis": {"ocr_high_resolution": false}
}
```

Workflow `mode: "off"` uses the original. Setting the deployment gate to `false` disables new
enhancement work; adaptive requests receive `NORMALIZATION_UNAVAILABLE`. Queued requests recheck
availability in the worker. An environment change does not interrupt in-flight jobs; use normal
run cancellation when needed. Historical derived sources remain readable after disabling the
feature and do not require native packages for viewing.

The independent `di_analysis.ocr_high_resolution` option requests Azure's high-resolution OCR
add-on. It works with local enhancement off, requires Azure DI, and can incur Azure add-on charges.

## Processing and worker boundaries

The versioned `adaptive-v1` profile conservatively adjusts orientation, skew and contrast. It
retains uncertain content and digital PDF pages. JPEG/PNG, TIFF frames and scanned PDF pages can
produce a derived PDF with unchanged page numbering. Office files and text bypass enhancement.
Blank-page skipping is separately opt-in; every page remains present in the derived document.

The existing runner, broker and queue are reused. Redis is not required. [CELERY.md](CELERY.md)
has worker commands. Linux/macOS prefork processes can render separate documents in parallel.
Windows threads/solo remain development options; PDFium calls and cleanup are serialized per
process because PDFium is not thread-safe. This does not serialize Azure calls. Do not add an
inner thread pool for PDF rendering.

Processing works page by page and checks cancellation between pages. Resource limits can cause
an explicit original-page fallback. Temporary files are cleaned up. Native process crashes still
use existing worker-loss recovery; Python cannot turn a terminated process into an inline fallback.

Resource limits are deployment settings, separate from the fixed transformation profile:
`DOCAI_IMAGE_NORMALIZATION_MAX_PIXELS` (20,000,000 per page),
`DOCAI_IMAGE_NORMALIZATION_MAX_DIMENSION` (10,000 pixels), and
`DOCAI_IMAGE_NORMALIZATION_MAX_OUTPUT_MB` (100 MB). Lower them for constrained workers. They do
not raise Azure's own input limits. Existing `DOCAI_MAX_PAGES` also applies.

## Sources, cache and review

Every run item references its exact layout. Derived inputs and layouts are immutable artifacts;
scalar cache keys are scoped to the document and processing configuration. Off/adaptive runs
cannot reuse one another's layouts. Fallback output is not a completed adaptive cache entry.

Source units are versioned with the layout artifact, preserving historical spans and ground-truth
links. Review requests carry the selected run so bytes, page metadata and geometry agree.
**View original** suppresses incompatible overlays and label capture. Rasterized PDFs use OCR
word-box selection: OCR output does not create a native PDF text layer. Core pypdf inspection
verifies native text on original digital pages in both off and adaptive modes; unknown and
scanned pages stay on OCR selection without importing the optional rendering libraries.

Model source indexes always use the original zero-based document indexes, including chunks
and segment subranges. Invalid or mismatched citations route to review rather than being
renumbered. Exports identify the layout artifact alongside source and ground-truth geometry.

Absence supersedes current field truth across representations. New geometric truth supersedes
the same representation and any document-wide absence; other representations retain historical
geometry. Capture and promotion share this rule, and evaluation selects the latest semantic value.

Processing-source access uses existing content roles. Per-project membership is still outside
the application's current organizational trust boundary. Provenance stores operations, page
decisions, dimensions, profile, source hash, time and bytes. Logs contain no document text.

## Outcomes and support

Upload rejection remains an ingestion concern. These outcomes apply to processing in one run:

| Code | Meaning | Response |
| --- | --- | --- |
| `NORMALIZATION_UNAVAILABLE` | Disabled gate, missing packages or incompatible configuration | Reject before dispatch or at worker preflight; correct configuration before retrying |
| `NORMALIZATION_FALLBACK` | Enhancement failed but the original can continue | Warning with affected original pages; continue |
| `NORMALIZATION_LIMIT_EXCEEDED` | Resource bound reached | Original fallback when safe, otherwise fail this document |
| `NORMALIZATION_FAILED` | Cannot safely continue | Fail at normalization; retry only when marked retryable |
| `INCOMPLETE_LAYOUT` | DI omitted a nonblank submitted page | Fail layout processing; never invent page content or successful extraction |
| `EMPTY_LAYOUT` | No readable content | Existing no-content failure; no LLM extraction |

Warnings appear in run-item details; succeeded items keep empty error fields. The admin error
panel groups fatal errors through existing machine codes. Page fallback does not itself fail the
run or create human-review fields; extraction validation and confidence rules still govern review.

## Verification and rollout

Tests use synthetic scans and mocked Azure responses; CI needs no service credentials or network.
Coverage includes transformations, conservative blanks, limits/fallback, optional dependency
isolation, source/cache versions, historical labeling, permissions and UI behavior. These tests
establish contracts and geometry, not OCR gains.

Before rollout, compare off/adaptive workflow versions against the same representative RND/QA
document set: clean files, difficult scans and sparse signed pages. Compare field accuracy,
missing fields, human-review rate, DI failures, fallback rate, elapsed time and pages sent to DI.
Inspect any content-loss regression. Enable later environments only when that comparison
justifies it. An "adjusted" page is not automatically an "improved" extraction.
