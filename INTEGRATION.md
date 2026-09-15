# Invoke a workflow and receive JSON

The API uses existing Django session authentication, permissions, ingestion validation, and the configured task runner. No frontend is required.

## Existing documents

POST /api/v1/workflows/{workflow-version-uuid}/invoke/
Content-Type: application/json

```json
{
  "dataset": "<dataset-uuid>",
  "document_ids": ["<document-uuid>"],
  "name": "Client extraction"
}
```

## New documents

POST to the same URL using multipart form data:
- dataset: dataset UUID in the workflow's project
- files: one or more file parts, repeating the files field
- name: optional run name

Supply either files or document_ids. Explicit document selection is required; omitted input never processes the entire dataset.

If any upload is rejected, HTTP 422 is returned and no run starts. Valid files from that batch remain in the dataset; accepted_document_ids in the error details identifies them for resubmission. Document validation and Azure processing errors are distinct.

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

The local SQLite/thread setup executes inline. Larger deployments can use the configured background runner. The endpoint does not impose a new execution timeout; align server/proxy timeouts or use a background worker for long jobs. Repeating POST creates another run; POST is not idempotent.

## Python client

From the repository backend environment:

```powershell
.\.venv\Scripts\python.exe ..\examples\invoke_workflow.py --base-url http://localhost:8000 --workflow WORKFLOW_UUID --dataset DATASET_UUID --username admin --output result.json path/to/document.pdf
```

The script prompts for the password, signs in using CSRF/session cookies, uploads files, polls if necessary, and saves the full JSON response. It exits unsuccessfully for a failed/partial/cancelled run. No Azure keys are sent to the client.

For repeated local testing, use the fuller tester and its config template:

```powershell
copy ..\examples\workflow_tester.config.example.json ..\examples\workflow_tester.config.json
.\.venv\Scripts\python.exe ..\examples\workflow_tester.py --config ..\examples\workflow_tester.config.json
```

You can also call it without a config file:

```powershell
.\.venv\Scripts\python.exe ..\examples\workflow_tester.py --workflow WORKFLOW_UUID --dataset DATASET_UUID --username admin --output result.json path\to\document.pdf
```

Preview the request without creating a run:

```powershell
.\.venv\Scripts\python.exe ..\examples\workflow_tester.py --workflow WORKFLOW_UUID --dataset DATASET_UUID --username admin --dry-run path\to\document.pdf
```

Interactive API documentation: http://localhost:8000/api/docs/

Authentication and project scoping remain those of the existing app. This change does not add API keys, tenant isolation, webhooks, or a public hosting deployment.
