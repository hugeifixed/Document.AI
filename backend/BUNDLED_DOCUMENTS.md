# Processing individual documents and mixed bundles

For a known individual W-2, use **Extraction only: structured** with the W-2 schema.
A short document that fits the configured limits goes directly to one extraction call, without
segmentation. The same applies to a known multi-page document that fits in one extraction request.

Use **Unbundle, classify and extract** for one uploaded file containing multiple business
documents. Categories route each identified instance to its extraction schema. Repeated W-2s
remain separate source instances; a multi-page note should remain one instance. This is not
automatic business deduplication.

Small bundles use one segmentation window when they fit. Overlapping windows are only needed
as input grows, and boundary adjudication runs only for missing or disputed boundary evidence.
There is no separate large-document runtime, size-mode switch, or extra provider call just
because large-bundle support is enabled. Checkpoint persistence adds bounded database/storage
work per actual model call; it does not call the model again. Read-only ownership checks avoid
row locks; publication still locks and rechecks the active claim.

The 600-page fixture is a stress scenario, not the default workload. Regression tests also
cover individual W-2 extraction and short documents, including their exact provider call counts.

## Enabling the changes

Apply the new database migrations (`python manage.py migrate`) and restart web and worker
processes together. New workflow versions use the validated `segmentation` object; remove the
retired `segmentation_strategy` key when copying older JSON. Published workflow snapshots are
not rewritten. The checked-in mixed-bundle example contains the new settings.

## Two different boundaries

**Segmentation** identifies document instances using bounded overlapping page windows. It uses
the snapshotted `segmentation` configuration and page evidence. Matching categories alone do
not prove continuation. Structural repairs, incomplete evidence and unresolved window decisions
are recorded and routed to review, with original page numbering retained.

**Extraction chunking** divides the text inside each identified instance into model calls.
Whole identified document keeps a short form together; character windows can handle long notes.
Section-aware uses headings/paragraphs, not embeddings or another document classifier. Fallback
applies only when the whole-document character threshold is exceeded. Output tokens are a
separate per-response limit, and character budgets are not exact token measurements.

Conflicting scalar fields use the configured reconciliation policy. Differing lists retain
their alternatives and require review: concatenating lists automatically can duplicate overlap
rows or lose legitimate repetitions. All fields keep their source document instance and evidence.

## Reading results

The document viewer lists each identified document with its instance number and page range.
Locate opens its first source page. The review queue includes grouping obligations even after
all flagged fields have decisions. Accepting fields or classifications does not approve a
boundary. When grouping is uncertain, inspect the source, adjust the workflow and reprocess;
there is no general-purpose visual boundary editor in this iteration.

If some extraction chunks fail validation, valid outputs remain inspectable but the item fails
with `INCOMPLETE_EXTRACTION`; an entirely invalid extraction keeps `INVALID_MODEL_OUTPUT`.
Neither outcome is delivery-ready.

Downloads remain available for diagnosis, including incomplete results. A completed job does
not mean complete OCR, correct grouping, complete extraction, or approved results. Use the
headless manifest's review counts (including segments), warnings, errors and item statuses;
follow its authorized, paginated resource links rather than assuming success means approval.

## Recovery and storage

DI submission and polling are separate. Saved operation references are scoped to the source
and effective analysis policy. Recoverable poll failures resume the known operation. Expired
operations use a bounded, explicitly recorded resubmission path. A crash between Azure accepting
a request and the application storing its reference can still cause repeat submission: exactly-once
external billing is not guaranteed.

Compatible completed LLM calls can be reused from guarded per-run-item checkpoints. Checkpoint
reuse does not count as another provider call; a real repeated request does. Cancellation and
stale worker claims prevent publication into a newer/terminal attempt. These rules are shared by
task runners; they do not turn an in-process development runner into a durable queue.

New layouts publish an immutable full artifact for processing and one private JSON artifact per
page/sheet for bounded viewer reads. This increases storage object count but avoids parsing an
entire large layout for every page change. Page artifacts are the sole viewer representation;
there is no legacy full-layout fallback or historical backfill. Retention/backups must include derived page files and
checkpoints with the source layouts. All artifacts use the configured Django storage backend.

The existing field/label viewer loads at most 200 entries per result. Document groups are
paginated independently; this change does not implement large-field-set browsing. Use paginated
API results or exports to inspect a larger result set during qualification, and treat complete
large-field-set UI review as a separate follow-up.

## Preflight before a live 600-page test

Record effective values from the actual web/worker environment; template defaults are not proof
of the deployed configuration. Use approved synthetic or redacted fixtures and an Azure tier
that supports the intended request size. The provider test is manual and may incur charges.

| Check | What to establish |
| --- | --- |
| Upload admission | `DOCAI_MAX_PAGES` defaults to 500 and `DOCAI_MAX_UPLOAD_MB` to 100; raise deliberately for the approved test, alongside proxy/request limits |
| Source truth | A page manifest lists the expected document instance/category and original ranges, including blank pages |
| Source/service limits | Confirm actual Azure tier, API version, supported formats, size/page limits and request quotas |
| Task runner | For recovery testing use the intended deployed durable worker/broker; one task still owns a file |
| Time budget | Record `CELERY_TASK_SOFT_TIME_LIMIT`/`CELERY_TASK_TIME_LIMIT`, pool support, provider timeouts/retries, and visibility/redelivery settings; no guessed universal timeout |
| Parallelism | One file with ten worker slots is not ten parallel segment tasks; first measure one file, then multiple uploads |
| Disk/storage | Originals, rendered/normalized scans, full/page layouts and checkpoints must fit local temporary space and shared storage; web and workers need consistent access |
| Memory | Measure process/container peak RSS and its limit; include rasterization and layout normalization, not only file size |
| Security | Keep source text, model responses, identifiers, keys and operation references out of ordinary logs and shared benchmark reports |

## Qualification record

Run digital, scanned and mixed fixtures at 50, 200, then 600 pages. Include repeated same-category
forms and notes crossing segmentation-window boundaries. Use a separate controlled test for
worker interruption after OCR and after several successful extraction chunks. Do not kill a
shared production worker as an experiment.

Record for every test:

- Source hash/size/page count and expected page-to-instance manifest.
- Commit, workflow/configuration hash, prompts, Azure deployments/API versions/tier, worker pool,
  concurrency, machine/container resources and storage/broker configuration (no credentials).
- Returned/missing/excluded pages, correct and incorrect boundaries/categories, uncertain ranges,
  missing/conflicting fields and evidence correctness against the manifest.
- Preparation/OCR/segmentation/extraction/persistence elapsed times; provider call counts and
  tokens; peak memory, temporary disk high-water mark and artifact sizes.
- Page-view latency after completion and query/storage-read behavior; expected bounded page reads.
- Interruption point, recovered checkpoints, repeated provider calls, duplicate results (must be
  zero), cancellation outcome and any unresolved work.

Agree live-model accuracy and latency targets before executing the benchmark. Deterministic
fixtures must match their exact expected manifest. Every page must be accounted for; do not
use 100% coverage as a substitute for correct document boundaries. Automated tests use provider
doubles and do not establish real Azure throughput or classification accuracy.

Multiple business documents on one physical page and interleaved/noncontiguous instances need
review; reliable automatic grouping for those cases is outside this iteration. Distributed
segment fan-out, new OCR providers, project membership/SSO and broader production deployment
gates remain separate work.
