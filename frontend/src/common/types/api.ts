export interface Envelope<T> {
  success: true;
  message: string;
  data: T;
  trace_id: string;
}
export interface ErrorDetail {
  field: string;
  message: string;
  code: string;
}
export interface ErrorEnvelope {
  success: false;
  message: string;
  errors: ErrorDetail[];
  error_code: string;
  trace_id: string;
}
export interface Page<T> {
  count: number;
  page: number;
  page_size: number;
  total_pages: number;
  results: T[];
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string;
  created: string;
}
export interface Dataset {
  id: string;
  project: string;
  name: string;
  split: string;
  is_production: boolean;
  document_count: number;
  created: string;
}
export interface CategoryDefinition {
  id: string;
  project: string;
  key: string;
  name: string;
  version: number;
}
export interface DocumentNavigation {
  scope: "run" | "dataset";
  run: string | null;
  previous: { id: string; original_filename: string } | null;
  next: { id: string; original_filename: string } | null;
}

export interface Document {
  navigation?: DocumentNavigation;
  id: string;
  dataset: string;
  dataset_name: string;
  original_filename: string;
  file_format: string;
  sha256: string;
  size_bytes: number;
  page_count: number;
  sheet_count: number;
  status: string;
  validation_errors: { code: string; message: string }[];
  created: string;
  modified: string;
  units?: SourceUnit[];
  processing_source?: ProcessingSource;
}
export interface ProcessingSource {
  url: string;
  file_format: string;
  layout_artifact: string | null;
  is_original: boolean;
}
export interface WorkflowCapabilities {
  defaults?: { azure_openai_deployment: string };
  image_normalization: { available: boolean; reason: string; profile: string };
  di_analysis: { ocr_high_resolution: boolean };
}
export interface InputQualityWarning {
  code: string;
  message: string;
  pages: number[];
  retryable: boolean;
}
export interface InputQualitySummary {
  mode: "off" | "adaptive";
  status: "off" | "bypassed" | "applied" | "fallback";
  profile: string;
  pages_examined: number;
  pages_adjusted: number;
  pages_skipped: number;
  duration_ms: number;
  warnings: InputQualityWarning[];
}
export interface SourceUnit {
  id: string;
  kind: "page" | "sheet";
  index: number;
  label: string;
  width: number | null;
  height: number | null;
  unit: string;
}
export interface Workflow {
  id: string;
  project: string;
  name: string;
  version: number;
  workflow_type: string;
  config: Record<string, unknown>;
  content_hash: string;
  status: string;
  approved_by: string | null;
  approved_at: string | null;
  created: string;
}
export interface PromptVersion {
  id: string;
  name: string;
  version: number;
  purpose: string;
  system_prompt: string;
  user_template: string;
  content_hash: string;
  created: string;
  created_by: string;
}
export interface PromptVersionReference {
  name: string;
  version: number;
}
export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "partial";
export type RunItemStatus = "queued" | "running" | "succeeded" | "failed" | "skipped";
export type ProcessingPhase =
  "queued" | "preparing_scans" | "reading_document" | "analyzing" | "saving_results" | "complete";
export type ProcessingOperation =
  | Exclude<ProcessingPhase, "analyzing">
  | "waiting_for_ocr"
  | "reusing_layout"
  | "identifying_groups"
  | "classifying"
  | "extracting"
  | "checking_evidence"
  | "retry_wait"
  | "failed"
  | "cancelled";
export interface ProcessingProgress {
  phase: ProcessingPhase;
  operation: ProcessingOperation;
  phase_started_at: string;
  operation_started_at: string;
  completed_phases: ProcessingPhase[];
  counter: { completed: number; total: number; unit: "pages" | "chunks" } | null;
  segment: { current: number; total: number } | null;
  retry_at: string | null;
}
export interface Run {
  id: string;
  project: string;
  workflow: string;
  workflow_name: string;
  workflow_version: number;
  workflow_type: string;
  dataset: string;
  dataset_name: string;
  name: string;
  status: RunStatus;
  stage: string;
  total_items: number;
  processed_items: number;
  failed_items: number;
  started_at: string | null;
  finished_at: string | null;
  cancel_requested: boolean;
  config_hash: string;
  prompt_versions: Record<string, PromptVersionReference>;
  used_prompt_versions?: Record<string, PromptVersionReference>;
  model_deployment: string;
  layout_adapter: string;
  llm_adapter: string;
  warnings: string[];
  errors: unknown[];
  created: string;
  metrics?: RunMetrics;
  config_snapshot?: Record<string, unknown>;
  guidance?: RunGuidance;
}
export interface RunItem {
  id: string;
  run: string;
  document: string;
  document_name: string;
  status: RunItemStatus;
  stage: string;
  attempts: number;
  error_code: string;
  error_message: string;
  retryable: boolean;
  duration_ms: number | null;
  correlation_id: string;
  layout_artifact?: string | null;
  input_quality?: Partial<InputQualitySummary>;
  processing_progress: ProcessingProgress | null;
  progress_updated_at: string | null;
  modified: string;
}
export interface LLMTokenTotals {
  calls: number;
  measured_calls: number;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
}
export interface LLMUsageStage extends LLMTokenTotals {
  stage: string;
}
export interface LLMUsageItem extends LLMTokenTotals {
  run_item: string;
  document: string;
  document_name: string;
}
export interface LLMUsageSummary extends LLMTokenTotals {
  run: string;
  finish_reasons: Record<string, number>;
  safety_outcomes: Partial<Record<"unknown" | "clear" | "flagged" | "blocked", number>>;
  by_stage: LLMUsageStage[];
  by_item: LLMUsageItem[];
}
export interface Progress {
  total: number;
  succeeded: number;
  failed: number;
  skipped: number;
  queued: number;
  running: number;
  remaining: number;
  stage: string;
  estimated_seconds_remaining: number | null;
  as_of: string;
  last_milestone_at: string | null;
  activity_items: RunItem[];
  estimated_finish_at: string | null;
}
export interface FieldMetrics {
  support: number;
  match: number;
  mismatch: number;
  missing: number;
  spurious: number;
  true_blank: number;
  accuracy: number | null;
  precision: number | null;
  recall: number | null;
  specificity: number | null;
  npv: number | null;
  f1: number | null;
  missing_rate: number | null;
  hallucinated_rate: number | null;
  numeric_mae?: number;
}
export interface RunMetrics {
  documents: number;
  processed: number;
  failed: number;
  has_ground_truth: boolean;
  extraction?: {
    aggregate: FieldMetrics;
    per_field: Record<string, FieldMetrics>;
    out_of_schema_labels?: Record<string, number>;
  };
  classification?: {
    labels: string[];
    matrix: number[][];
    accuracy: number;
    macro: { f1: number | null };
    micro: { f1: number | null };
    weighted: { f1: number | null };
    other_or_unclassified_rate: number | null;
    per_class: Record<string, { support: number; precision: number | null; recall: number | null; f1: number | null }>;
  };
  segmentation?: { aggregate: Record<string, number | null>; per_document: Record<string, unknown>[] };
  quality_indicators?: {
    kind: string;
    note: string;
    document_count: number;
    per_field: Record<string, Record<string, unknown>>;
  };
}
export interface Span {
  id: string;
  unit_index: number;
  unit_kind: string;
  text: string;
  polygon: number[];
  word_ids: string[];
  cell_range: string;
  mapping_method: string;
  match_score: number | null;
  offset_start: number | null;
  offset_end: number | null;
}
export interface ExtractedField {
  id: string;
  run: string;
  document: string;
  document_name: string;
  segment: string | null;
  segment_index?: number | null;
  segment_start_unit?: number | null;
  segment_end_unit?: number | null;
  name: string;
  field_type: string;
  list_candidates?: { value: string | null }[] | string;
  raw_value: string | null;
  normalized_value: string | null;
  reviewed_value: string | null;
  score: number | null;
  source_text: string;
  method: string;
  strategy: string;
  fallback_used: string;
  model_deployment: string;
  prompt: string | null;
  schema: string | null;
  validation_status: string;
  validation_messages: string[];
  suggested_correction: string | null;
  review_status: string;
  grounded: boolean;
  spans: Span[];
  modified: string;
}
export interface Classification {
  id: string;
  run: string;
  document: string;
  document_name: string;
  segment: string | null;
  category: string;
  reviewed_category: string;
  score: number | null;
  method: string;
  rule_score: number | null;
  llm_evidence: string;
  review_status: string;
  spans: Span[];
}
export interface Segment {
  id: string;
  run: string;
  document: string;
  document_name: string;
  index: number;
  start_unit: number;
  end_unit: number;
  category: string;
  score: number | null;
  method: string;
  review_status: string;
  boundary_review_reasons?: string[];
}
export interface Label {
  id: string;
  document: string;
  unit_index: number | null;
  kind: string;
  field_name: string;
  category: string;
  expected_value: string | null;
  is_absent: boolean;
  mapping_method: string;
  match_score: number | null;
  mapping_exceptions: string[];
  version: number;
  status: string;
  spans: Span[];
  created: string;
}
export interface Evaluation {
  id: string;
  project: string;
  run: string | null;
  run_name: string;
  dataset: string;
  metrics: RunMetrics;
  has_ground_truth: boolean;
  created: string;
}
export interface RunGuidance {
  review: { fields: number; classifications: number; segments?: number };
  results: number;
  ground_truth: { labels: number; documents: number };
  evaluations: { count: number; latest_id: string | null; has_ground_truth: boolean | null };
  export_ready: boolean;
}
export interface JourneyGuidance {
  dataset: { id: string; name: string; split: Dataset["split"]; is_production: boolean } | null;
  documents: { total: number; runnable: number; blocked: number; new_for_run: number };
  workflows: {
    runnable: number;
    approved: number;
    draft: number;
    suggested: { id: string; name: string; version: number; status: string } | null;
  };
  latest_run: {
    id: string;
    name: string;
    workflow: string;
    status: RunStatus;
    processed: number;
    total: number;
    failed: number;
    created: string;
    guidance: RunGuidance;
  } | null;
}
export interface Dashboard {
  projects: number;
  datasets: number;
  configurations: number;
  runs: Record<string, number>;
  evaluations: number;
  review_queue: { fields: number; classifications: number; segments?: number };
  recent_errors: { run_id: string; document: string; code: string; message: string; at: string }[];
  recent_runs: {
    id: string;
    name: string;
    status: string;
    workflow: string;
    processed: number;
    total: number;
    created: string;
  }[];
  guidance: JourneyGuidance;
}
export interface Me {
  username: string;
  is_staff: boolean;
  roles: string[];
  platform_version: string;
  adapters: { layout: string; llm: string; task_runner: string };
  tools: { request_profiler: string | null };
}
export interface LayoutUnit {
  kind: "page" | "sheet";
  index: number;
  number?: number;
  width?: number;
  height?: number;
  unit?: string;
  content: string;
  has_text_layer?: boolean;
  words?: { id: string; text: string; polygon: number[] }[];
  cells?: { id: string; ref: string; row: number; col: number; value: string | null; formula: string | null }[];
  row_count?: number;
  col_count?: number;
  name?: string;
}

export interface MetricsMeta {
  start_date: string;
  end_date: string;
  timezone: "UTC";
  as_of: string;
  cache_ttl_seconds: number;
  applied_filters: Record<string, string>;
}
export interface MetricsProcessingDay {
  date: string;
  completed_jobs: number;
  succeeded: number;
  failed: number;
  duration_sample_count: number;
  median_duration_ms: number | null;
  p95_duration_ms: number | null;
}
export interface MetricsRunOutcomes {
  succeeded: number;
  failed: number;
  partial: number;
  cancelled: number;
}
export interface Metrics {
  meta: MetricsMeta;
  processing: {
    completed_jobs: number;
    duration_sample_count: number;
    median_duration_ms: number | null;
    p95_duration_ms: number | null;
    daily: MetricsProcessingDay[];
    by_document_type: { key: string; label: string; executions: number }[];
    failures_by_phase: { key: string; label: string; count: number }[];
    document_type_options: { key: string; label: string }[];
  };
  runs: MetricsRunOutcomes & { success_rate: number | null; daily: (MetricsRunOutcomes & { date: string })[] };
  review: {
    backlog_fields: number;
    backlog_classifications: number;
    backlog_segments?: number;
    backlog_documents: number;
    decision_count: number;
    field_decision_count: number;
    field_correction_count: number;
    field_correction_rate: number | null;
    daily: { date: string; field_decisions: number; classification_decisions: number }[];
  };
}
export interface MetricsUsage {
  meta: MetricsMeta;
  calls: number;
  measured_calls: number;
  total_tokens: number | null;
  daily: { date: string; calls: number; measured_calls: number; total_tokens: number | null }[];
  filter_options: { providers: string[]; deployments: string[]; stages: string[] };
}
