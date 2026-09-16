# Integrate with DocAI workflows

Applications and agents can invoke a pinned, approved workflow without using the React frontend. The public
integration surface is REST with an OpenAPI 3.2 contract at `/api/schema/` and interactive documentation at
`/api/docs/`. MCP, webhooks, staged Blob uploads, and inbound OIDC are later integration layers rather than part of
this contract.

## Current authentication boundary

RND uses the same Django identities and roles as the browser. The example client signs in through the session API
and sends a CSRF token on mutations. A deployment can explicitly enable HTTP Basic authentication for service
clients with `DOCAI_ENABLE_BASIC_AUTH=true`, but only behind HTTPS. Azure service-principal and managed-identity
credentials authenticate DocAI's outbound provider calls; they do not authenticate callers to this API.

Views authorize `request.user`, which is the stable seam for a later Entra/OIDC authenticator. Replacing how an
identity is established should not change the workflow, idempotency, upload, polling, or result contracts. Current
roles are global and suitable only for one trusted team; project membership must be enforced before separate lines
of business share a deployment.

## 1. Inspect the callable workflow

```http
GET /api/v1/workflows/{workflow-version-uuid}/contract/
```

Only approved processing workflow versions have a contract; evaluation workflows are not callable through this
endpoint. The contract distinguishes globally `ingestible_formats` from `processable_formats` supported by the
effective layout adapter. A pypdf deployment can store images or DOCX, for example, but cannot promise to process
them until Azure DI is selected. The contract also describes limits, invocation modes, possible result resources,
categories, and extraction schemas. It intentionally excludes prompts, credentials, provider settings, and model
deployment internals. Pin the returned workflow UUID and `config_hash` in the caller's own configuration so a newly
approved version is an explicit integration change.

## 2. Upload documents first

The canonical flow stores documents before invoking a workflow:

```http
POST /api/v1/datasets/{dataset-uuid}/upload/
Content-Type: multipart/form-data

files=<one or more repeated file parts>
```

The response contains `accepted`, `reused_document_ids`, and `rejected`:

- `201 Created`: at least one new document was stored. Rejections may also be present.
- `200 OK`: every accepted file already existed byte-for-byte in this dataset.
- `422 Unprocessable Entity`: no file was accepted.

An identical file in the same dataset is a successful reuse, even when its filename differs. Its existing document
appears in `accepted`, and its UUID appears in `reused_document_ids`. Upload retries therefore do not create duplicate
documents. A caller should inspect `rejected` before deciding whether to invoke the accepted subset.

This two-step flow is preferred because document IDs are durable, separately inspectable, and reusable across runs.
The invoke endpoint still accepts repeated multipart `files` as a convenience for simple clients. If one file in a
multipart invocation is rejected, no run starts; accepted documents remain in the dataset and their IDs are returned
in the validation details.

## 3. Invoke by document ID

```http
POST /api/v1/workflows/{workflow-version-uuid}/invoke/
Content-Type: application/json
Idempotency-Key: <one key for this logical invocation>

{
  "dataset": "<dataset-uuid>",
  "document_ids": ["<document-uuid>"],
  "name": "September W-2 batch",
  "client_reference": "upstream-job-1042"
}
```

The workflow must be approved, and every document must belong to the supplied dataset in the workflow's project.
Explicit document selection is required; omitting it never processes the entire dataset. `client_reference` is an
optional caller-owned job, case, or correlation value. It is returned in the operation handle and manifest and can
filter the runs collection.

Successful acceptance always returns `202 Accepted`, including a replay after the run has finished:

```json
{
  "success": true,
  "data": {
    "run_id": "<run-uuid>",
    "status": "queued",
    "client_reference": "upstream-job-1042",
    "idempotency_expires_at": "2026-10-15T14:00:00Z",
    "links": {
      "results": "https://docai.example/api/v1/runs/<run-uuid>/results/",
      "run": "https://docai.example/api/v1/runs/<run-uuid>/",
      "progress": "https://docai.example/api/v1/runs/<run-uuid>/progress/",
      "run_items": "https://docai.example/api/v1/run-items/?run=<run-uuid>",
      "fields": "https://docai.example/api/v1/fields/?run=<run-uuid>",
      "classifications": "https://docai.example/api/v1/classifications/?run=<run-uuid>",
      "segments": "https://docai.example/api/v1/segments/?run=<run-uuid>"
    }
  }
}
```

The response includes `Location: <links.results>` and `Retry-After: 2`. Treat `run_id` as the operation identifier;
do not hold the POST connection open for processing.

## Idempotency and safe retries

Generate one `Idempotency-Key` for a logical invocation before the first POST, store it with the upstream job, and
reuse it after timeouts, dropped connections, or retryable dispatch failures. Do not generate a new key merely
because the first response was lost.

The server guarantees the key for 30 days and returns `idempotency_expires_at`. Its scope is the authenticated user
and pinned workflow version. The request fingerprint covers the dataset, run name, `client_reference`, sorted
document IDs, or multipart file hashes, sizes, and filenames.

- Same key and same input: `202`, the original run handle, and `Idempotency-Replayed: true`.
- Same key and different input: `409 IDEMPOTENCY_KEY_REUSED`; create a new key for the new logical request.
- Same request while documents are still being accepted: `409 INVOCATION_IN_PROGRESS`; retry the same POST after
  `Retry-After`.
- Dispatch unavailable after a run exists: retry the same POST and key. A short database lease serializes dispatch;
  an active dispatcher returns the existing `202` handle, and an expired dispatcher lease lets the retry schedule
  the existing queued run rather than create another one.
- Validation or upload failure before a run exists: the same key replays the original failure. Correct the input and
  use a new key.

The short acceptance/dispatch lease is recovery state, separate from the 30-day replay expiry. If a web process
stops after accepting multipart data or attaching a run, an identical retry can take over after the lease expires;
uploaded bytes are matched to the existing dataset document. Retiring a workflow blocks new keys but does not break
an exact retry: the original handle remains available and its `workflow_contract` link becomes `null` because that
contract is no longer callable. Soft-deleting the linked dataset likewise blocks new work while preserving exact
replay of an existing operation handle; changed fingerprint inputs still return `IDEMPOTENCY_KEY_REUSED`.

The repository client preflights the approved contract by default. To resume an invocation after that workflow has
been retired, use its explicit `--resume-replay` mode with the exact original document IDs, idempotency key, run name,
and client reference. This mode skips contract preflight and upload only; it sends the original fingerprint inputs
back to the same invoke endpoint, where any mismatch is rejected:

```bash
python examples/workflow_tester.py --resume-replay \
  --workflow ORIGINAL_WORKFLOW_UUID --dataset ORIGINAL_DATASET_UUID --username integration-user \
  --document-id ORIGINAL_DOCUMENT_UUID --idempotency-key ORIGINAL_KEY \
  --name "ORIGINAL RUN NAME" --client-reference "ORIGINAL REFERENCE"
```

Use `--client-reference ""` when the original request used an empty value. Resume mode cannot upload files or create
a new logical request; omit it for every normal invocation.

The cleanup command deletes expired reservations only after their run is terminal or when acceptance failed before
a run was created:

```bash
python manage.py cleanup_expired_invocations
```

Schedule it after the 30-day window according to institutional retention policy. Active operations keep their
reservation even when its nominal expiry has passed.

## 4. Poll the bounded manifest

Poll `links.results` after `Retry-After`:

```http
GET /api/v1/runs/{run-uuid}/results/
If-None-Match: W/"<semantic-etag from the prior response>"
```

Pending runs return `202` and `Retry-After`; terminal runs return `200`. The weak ETag covers the semantic manifest,
not the envelope's per-response trace ID. An unchanged manifest returns `304 Not Modified`, so keep the previous
representation and honor its new `Retry-After`. The manifest is deliberately bounded:
it contains lifecycle state, aggregate counts, review counts, and capped warning/error summaries. `completed=true`
means the status is `succeeded`, `partial`, `failed`, or `cancelled`; inspect `status`, warnings, and errors rather
than relying only on HTTP 200.

The manifest never embeds an unbounded result package. Follow its paginated `run_items`, `fields`, `classifications`,
and `segments` links until `data.next` is null. Use an export link when a complete JSON, CSV, or XLSX delivery package
is more suitable. Preserve the caller's authentication on same-origin links only.

Errors use the common envelope and include stable `error_code`, `retryable`, `trace_id`, and code-preserving details.
Log the `trace_id` with the caller's `client_reference`; do not parse human messages as machine state.

## Execution behavior

All HTTP run creation, execution, retry, and headless invocation paths return an asynchronous operation handle for
every task runner.

- Local `sync` and `thread` settings use one bounded, process-local coordinator per web process. It accepts runs
  outside the request, executes one run at a time, and lets the thread runner process document items up to
  `DOCAI_MAX_WORKERS` on a server database. SQLite processes items sequentially. This queue is convenient but
  best-effort: a web-process restart can abandon locally queued work.
- Celery publishes one durable broker task per document. Worker pool capacity controls document parallelism, and
  the database remains the source of run state; no Celery result backend is required.

When local queued work or a worker is lost, `python manage.py recover_stalled_runs` converts sufficiently old items
to visible retryable failures. Correct the runtime problem and use the existing run retry action. When initial
dispatch itself fails, the run records `dispatch_failed`; retrying the original idempotent POST safely attempts the
same run again.

Use Celery with a network broker before running multiple web/worker hosts or requiring durable automatic recovery.
See `backend/CELERY.md` in the repository for pool, broker, and recovery details.

## Python example client

Install the pinned client dependency from `backend/`:

```bash
uv sync --extra integration
```

Then run the document-first client from the repository root. It preflights the approved workflow contract, uploads,
invokes with JSON document IDs, polls with ETags, follows every paginated result link, and saves one JSON file
containing the manifest and collections:

```bash
uv run --project backend --extra integration python examples/invoke_workflow.py \
  --base-url http://localhost:8000 \
  --workflow WORKFLOW_UUID \
  --dataset DATASET_UUID \
  --username admin \
  --client-reference upstream-job-1042 \
  --output result.json \
  path/to/document.pdf
```

The script prints its generated idempotency key. Pass that same value with `--idempotency-key` after an uncertain
transport failure. `workflow_tester.py` provides the same implementation plus a JSON configuration template:

```powershell
Copy-Item examples/workflow_tester.config.example.json examples/workflow_tester.config.json
uv run --project backend --extra integration python examples/workflow_tester.py `
  --config examples/workflow_tester.config.json
```

Use `--document-id UUID` for an already stored document. Use `--multipart-invoke` only when a one-request convenience
call is required. `--dry-run` prints the intended requests without signing in, uploading, or creating a run.
