import type { Page, Route } from "@playwright/test";

export const E2E_USER = {
  username: "e2e.operator",
  is_staff: true,
  roles: ["docai_operators", "docai_reviewers", "docai_approvers"],
  platform_version: "1",
  adapters: { layout: "mock", llm: "mock", task_runner: "sync" },
  tools: { request_profiler: "/admin/profiler/" },
};

export const PROJECT = {
  id: "project-1",
  name: "Document processing",
  slug: "document-processing",
  description: "",
  created: "2026-09-11T12:00:00Z",
};

export const DATASET = {
  id: "dataset-1",
  project: "project-1",
  name: "Information For Navigation - Mines Site Development Documents",
  split: "dev",
  is_production: false,
  document_count: 1,
  created: "2026-09-11T12:00:00Z",
};

export const DOCUMENT = {
  id: "document-1",
  dataset: "dataset-1",
  dataset_name: DATASET.name,
  original_filename:
    "quarterly-statement-with-a-deliberately-long-enterprise-document-name-that-must-not-expand-the-page.txt",
  file_format: "txt",
  sha256: "abc123",
  size_bytes: 12,
  page_count: 1,
  sheet_count: 0,
  status: "processed",
  validation_errors: [],
  created: "2026-09-11T12:00:00Z",
  modified: "2026-09-11T12:00:00Z",
  units: [{ id: "unit-1", kind: "page", index: 0, label: "Page 1", width: 612, height: 792, unit: "pt" }],
};

export const WORKFLOW = {
  id: "workflow-1",
  project: "project-1",
  name: "Extract statements",
  version: 1,
  workflow_type: "extract_structured",
  config: {},
  content_hash: "sha256:1234567890abcdef",
  status: "approved",
  approved_by: "approver",
  approved_at: "2026-09-11T11:00:00Z",
  created: "2026-09-11T10:00:00Z",
};

export const RUN = {
  id: "run-1",
  project: "project-1",
  workflow: "workflow-1",
  workflow_name: "Extract statements",
  workflow_type: "extract_structured",
  dataset: "dataset-1",
  dataset_name: DATASET.name,
  name: "Browser run",
  status: "running",
  stage: "processing",
  total_items: 1,
  processed_items: 0,
  failed_items: 0,
  started_at: "2026-09-11T12:00:00Z",
  finished_at: null,
  cancel_requested: false,
  config_hash: "sha256:1234567890abcdef",
  prompt_versions: {},
  model_deployment: "",
  layout_adapter: "mock",
  llm_adapter: "mock",
  warnings: [],
  errors: [],
  created: "2026-09-11T12:00:00Z",
};

export const FIELD = {
  id: "field-1",
  run: "run-1",
  document: "document-1",
  document_name: DOCUMENT.original_filename,
  segment: null,
  name: "account_holder",
  field_type: "string",
  raw_value: "Daniel Silva",
  normalized_value: "Daniel Silva",
  reviewed_value: null,
  score: 0.72,
  source_text: "Daniel Silva",
  method: "llm",
  strategy: "whole_document",
  fallback_used: "",
  model_deployment: "model",
  prompt: null,
  schema: null,
  validation_status: "valid",
  validation_messages: [],
  suggested_correction: null,
  review_status: "needs_review",
  grounded: true,
  spans: [],
  modified: "2026-09-11T12:00:00Z",
};

export const DASHBOARD = {
  projects: 1,
  datasets: 1,
  configurations: 1,
  runs: { running: 0, succeeded: 1 },
  evaluations: 0,
  review_queue: { fields: 1, classifications: 0 },
  recent_errors: [],
  recent_runs: [],
  guidance: {
    dataset: { id: DATASET.id, name: DATASET.name, split: DATASET.split, is_production: false },
    documents: { total: 1, runnable: 1, blocked: 0, new_for_run: 1 },
    workflows: {
      runnable: 1,
      approved: 1,
      draft: 0,
      suggested: { id: WORKFLOW.id, name: WORKFLOW.name, version: WORKFLOW.version, status: WORKFLOW.status },
    },
    latest_run: null,
  },
};

export function apiPage<T>(results: T[]) {
  return { count: results.length, page: 1, page_size: 25, total_pages: results.length ? 1 : 0, results };
}

export async function fulfillApi(route: Route, data: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify({ success: status < 400, message: "ok", data, trace_id: "e2e" }),
  });
}

export async function prepareWorkspace(page: Page, username = E2E_USER.username) {
  await page.addInitScript(
    ({ user, preferences, workingContext }) => {
      localStorage.setItem(`docai-product-tour:1:${encodeURIComponent(user)}`, "acknowledged");
      localStorage.setItem("docai-prefs", JSON.stringify({ state: preferences, version: 0 }));
      localStorage.setItem("docai-working-context", JSON.stringify({ state: workingContext, version: 0 }));
    },
    {
      user: username,
      preferences: {
        theme: "light",
        pageSize: 25,
        sidebarHidden: false,
      },
      workingContext: { projectId: PROJECT.id, datasetId: DATASET.id },
    },
  );
}
