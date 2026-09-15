import type { Metrics, MetricsUsage } from "@/common/types/api";
export const metrics: Metrics = {
  meta: {
    start_date: "2026-09-01",
    end_date: "2026-09-01",
    timezone: "UTC",
    as_of: "2026-09-01T12:00:00Z",
    cache_ttl_seconds: 60,
    applied_filters: {},
  },
  processing: {
    completed_jobs: 9,
    duration_sample_count: 8,
    median_duration_ms: 2000,
    p95_duration_ms: 5000,
    daily: [
      {
        date: "2026-09-01",
        completed_jobs: 9,
        succeeded: 7,
        failed: 2,
        duration_sample_count: 8,
        median_duration_ms: 2000,
        p95_duration_ms: 5000,
      },
    ],
    by_document_type: [{ key: "invoice", label: "Invoice", executions: 7 }],
    failures_by_phase: [{ key: "unknown", label: "Unknown", count: 2 }],
    document_type_options: [{ key: "invoice", label: "Invoice" }],
  },
  runs: {
    succeeded: 2,
    failed: 1,
    partial: 1,
    cancelled: 1,
    success_rate: 50,
    daily: [{ date: "2026-09-01", succeeded: 2, failed: 1, partial: 1, cancelled: 1 }],
  },
  review: {
    backlog_fields: 4,
    backlog_classifications: 2,
    backlog_documents: 3,
    decision_count: 8,
    field_decision_count: 5,
    field_correction_count: 1,
    field_correction_rate: 20,
    daily: [{ date: "2026-09-01", field_decisions: 5, classification_decisions: 3 }],
  },
};
export const usage: MetricsUsage = {
  meta: metrics.meta,
  calls: 5,
  measured_calls: 3,
  total_tokens: 600,
  daily: [{ date: "2026-09-01", calls: 5, measured_calls: 3, total_tokens: 600 }],
  filter_options: { providers: ["azure"], deployments: ["extract"], stages: ["extraction"] },
};
