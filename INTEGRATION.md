# Invoke a workflow and receive JSON

The API uses existing Django session authentication, permissions, ingestion validation, and the configured task runner. No frontend is required.

## Existing documents

POST /api/v1/workflows/{workflow-version-uuid}/invoke/
Content-Type: application/json
Idempotency-Key: <client-generated-unique-value>

```json
{
  "dataset": "<dataset-uuid>",
  "document_ids": ["<document-uuid>"],
  "name": "Client extraction"
}
```

## New documents

POST to the same URL using multipart form data:
- Idempotency-Key header: one unique value for this logical invocation
- dataset: dataset UUID in the workflow's project
- files: one or more file parts, repeating the files field
- name: optional run name

Supply either files or document_ids. Explicit document selection is required; omitted input never processes the entire dataset.

If any upload is rejected, HTTP 422 is returned and no run starts. Valid files from that batch remain in the dataset;
`accepted_document_ids` in the error details identifies them for resubmission. Repeating the request with the same
idempotency key replays that failure without uploading the accepted documents again. Use a new key for a corrected
request. Document validation and Azure processing errors are distinct.

## Safe retries

`Idempotency-Key` is required and may contain 1-128 visible token characters. Generate it once for a logical call
and preserve it across connection and gateway retries. The key is scoped to the authenticated user and pinned
workflow version.

- Same key and same input: returns the original run, current run status, or original upload failure.
- Same key and different input: HTTP 409 `IDEMPOTENCY_KEY_REUSED`.
- Same request while its uploads are still being accepted: HTTP 409 `INVOCATION_IN_PROGRESS`; retry the same POST
  after the `Retry-After` delay.

File identity uses streamed SHA-256 values, filenames, and sizes. Existing-document identity uses sorted document
UUIDs. Raw file content and credentials are never stored in the invocation reservation.

## Response

Responses use the application's existing envelope. Read data.completed and data.status, not just the outer success flag.

```json
{
  "success": true,
  "data": {
    "run_id": "<run-uuid>",
    "status": "succeeded",
    "completed": true,
    "workflow": {
      "id": "<workflow-version-uuid>",
      "name": "w9",
      "version": 2,
      "config_hash": "sha256:..."
    },
    "results_url": "http://localhost:8000/api/v1/runs/<run-uuid>/results/",
    "results": {
      "fields": [],
      "classifications": [],
      "segments": [],
      "errors": []
    },
    "errors": []
  }
}
```

HTTP 200 means processing is terminal, including partial, failed, or cancelled runs. Inspect status and both error collections. Extracted fields retain document and segment IDs, normalized/raw/reviewed values, list candidates, scores, review state, and source evidence. Table/list extraction is represented by the workflow's extracted fields; this endpoint does not export every raw OCR table.

HTTP 202 means processing is pending or running. results is null. Poll the results_url using GET, honoring Retry-After. Each poll returns the same response shape. GET /api/v1/runs/{run-uuid}/results/ also works for existing runs.

The local SQLite/thread setup processes sequentially within the web request lifecycle and returns after completion.
Larger deployments can use the configured background runner. The endpoint does not impose a new execution timeout;
align server/proxy timeouts or use a background worker for long jobs.

## Python client

Install the small client-only extra once from `backend/` with `uv sync --extra integration`. Then run:

```powershell
uv run --extra integration python ../examples/invoke_workflow.py --base-url http://localhost:8000 --workflow WORKFLOW_UUID --dataset DATASET_UUID --username admin --output result.json path/to/document.pdf
```

The script prompts for the password, signs in using CSRF/session cookies, generates and prints an idempotency key,
uploads files, polls if necessary, and saves the full JSON response. If a transport retry is needed, pass the printed
value back with `--idempotency-key`. It exits unsuccessfully for a failed/partial/cancelled run. No Azure keys are
sent to the client.

For repeated local testing, use the fuller tester and its config template:

```powershell
Copy-Item ../examples/workflow_tester.config.example.json ../examples/workflow_tester.config.json
uv run --extra integration python ../examples/workflow_tester.py --config ../examples/workflow_tester.config.json
```

You can also call it without a config file:

```powershell
uv run --extra integration python ../examples/workflow_tester.py --workflow WORKFLOW_UUID --dataset DATASET_UUID --username admin --output result.json path/to/document.pdf
```

Preview the request without creating a run:

```powershell
uv run --extra integration python ../examples/workflow_tester.py --workflow WORKFLOW_UUID --dataset DATASET_UUID --username admin --dry-run path/to/document.pdf
```

Interactive API documentation: http://localhost:8000/api/docs/

Authentication and project scoping remain those of the existing app. RND supports Django sessions and opt-in Basic
authentication over HTTPS. Azure service-principal or managed-identity credentials authenticate outbound provider
calls; they do not authenticate callers to this API. Project membership, Entra/OIDC caller authentication, webhooks,
and public hosting are outside the current trusted-team boundary.
