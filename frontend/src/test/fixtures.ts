import type {
  Dashboard,
  Dataset,
  Document,
  Evaluation,
  ExtractedField,
  Label,
  Me,
  Page,
  Project,
  Run,
  RunItem,
  Workflow,
} from "@/api/types";

export function page<T>(results: T[], overrides: Partial<Omit<Page<T>, "results">> = {}): Page<T> {
  return {
    count: results.length,
    page: 1,
    page_size: 25,
    total_pages: results.length ? 1 : 0,
    results,
    ...overrides,
  };
}

export function testUser(overrides: Partial<Me> = {}): Me {
  return {
    username: "reviewer",
    is_staff: false,
    roles: ["docai_operators", "docai_reviewers", "docai_approvers"],
    platform_version: "1",
    adapters: { layout: "mock", llm: "mock", task_runner: "sync" },
    tools: { request_profiler: null },
    ...overrides,
  };
}

export function testProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "project-1",
    name: "Document processing",
    slug: "document-processing",
    description: "",
    created: "2026-09-11T12:00:00Z",
    ...overrides,
  };
}

export function testDataset(overrides: Partial<Dataset> = {}): Dataset {
  return {
    id: "dataset-1",
    project: "project-1",
    name: "Quarterly statements",
    split: "dev",
    is_production: false,
    document_count: 1,
    created: "2026-09-11T12:00:00Z",
    ...overrides,
  };
}

export function testDocument(overrides: Partial<Document> = {}): Document {
  return {
    id: "document-1",
    dataset: "dataset-1",
    dataset_name: "Quarterly statements",
    original_filename: "statement.txt",
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
    ...overrides,
  };
}

export function testWorkflow(overrides: Partial<Workflow> = {}): Workflow {
  return {
    id: "workflow-1",
    project: "project-1",
    name: "Extract statements",
    version: 1,
    workflow_type: "extract_structured",
    config: {},
    content_hash: "sha256:1234567890abcdef",
    status: "draft",
    approved_by: null,
    approved_at: null,
    created: "2026-09-11T12:00:00Z",
    ...overrides,
  };
}

export function testRun(overrides: Partial<Run> = {}): Run {
  return {
    id: "run-1",
    project: "project-1",
    workflow: "workflow-1",
    workflow_name: "Extract statements",
    workflow_type: "extract_structured",
    dataset: "dataset-1",
    dataset_name: "Quarterly statements",
    name: "September run",
    status: "running",
    stage: "processing",
    total_items: 4,
    processed_items: 1,
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
    guidance: {
      review: { fields: 0, classifications: 0 },
      results: 1,
      ground_truth: { labels: 0, documents: 0 },
      evaluations: { count: 0, latest_id: null, has_ground_truth: null },
      export_ready: false,
    },
    ...overrides,
  };
}

export function testRunItem(overrides: Partial<RunItem> = {}): RunItem {
  return {
    id: "item-1",
    run: "run-1",
    document: "document-1",
    document_name: "statement.txt",
    status: "succeeded",
    stage: "complete",
    attempts: 1,
    error_code: "",
    error_message: "",
    retryable: false,
    duration_ms: 250,
    correlation_id: "correlation-1",
    modified: "2026-09-11T12:00:00Z",
    ...overrides,
  };
}

export function testField(overrides: Partial<ExtractedField> = {}): ExtractedField {
  return {
    id: "field-1",
    run: "run-1",
    document: "document-1",
    document_name: "statement.txt",
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
    ...overrides,
  };
}

export function testLabel(overrides: Partial<Label> = {}): Label {
  return {
    id: "label-1",
    document: "document-1",
    unit_index: null,
    kind: "field",
    field_name: "account_holder",
    category: "",
    expected_value: null,
    is_absent: true,
    mapping_method: "absent",
    match_score: null,
    mapping_exceptions: [],
    version: 1,
    status: "draft",
    spans: [],
    created: "2026-09-11T12:00:00Z",
    ...overrides,
  };
}

export function testEvaluation(overrides: Partial<Evaluation> = {}): Evaluation {
  return {
    id: "evaluation-1",
    project: "project-1",
    run: "run-1",
    run_name: "September run",
    dataset: "dataset-1",
    metrics: { documents: 1, processed: 1, failed: 0, has_ground_truth: true },
    has_ground_truth: true,
    created: "2026-09-11T12:00:00Z",
    ...overrides,
  };
}

export function testDashboard(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    projects: 1,
    datasets: 1,
    configurations: 2,
    runs: { running: 1, succeeded: 3, failed: 1 },
    evaluations: 1,
    review_queue: { fields: 2, classifications: 1 },
    recent_errors: [
      {
        run_id: "run-1",
        document: "failed-statement.pdf",
        code: "LAYOUT_FAILED",
        message: "Layout analysis failed",
        at: "2026-09-11T12:00:00Z",
      },
    ],
    recent_runs: [
      {
        id: "run-1",
        name: "September run",
        status: "running",
        workflow: "Extract statements",
        processed: 1,
        total: 4,
        created: "2026-09-11T12:00:00Z",
      },
    ],
    guidance: {
      dataset: {
        id: "dataset-1",
        name: "Quarterly statements",
        split: "dev",
        is_production: false,
      },
      documents: { total: 1, runnable: 1, blocked: 0, new_for_run: 0 },
      workflows: {
        runnable: 1,
        approved: 1,
        draft: 0,
        suggested: { id: "workflow-1", name: "Extract statements", version: 1, status: "approved" },
      },
      latest_run: {
        id: "run-1",
        name: "September run",
        workflow: "Extract statements",
        status: "running",
        processed: 1,
        total: 4,
        failed: 0,
        created: "2026-09-11T12:00:00Z",
        guidance: {
          review: { fields: 2, classifications: 1 },
          results: 1,
          ground_truth: { labels: 0, documents: 0 },
          evaluations: { count: 0, latest_id: null, has_ground_truth: null },
          export_ready: false,
        },
      },
    },
    ...overrides,
  };
}
