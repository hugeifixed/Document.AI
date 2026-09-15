export type MetricsRange = "today" | "7d" | "30d" | "90d" | "custom";
export interface MetricsScope {
  project?: string;
  dataset?: string;
}
export interface DateFilters extends MetricsScope {
  range: MetricsRange;
  start?: string;
  end?: string;
}
export interface ProcessingFilters extends DateFilters {
  document_type?: string;
  status?: "succeeded" | "failed";
}
export interface UsageFilters extends DateFilters {
  provider?: string;
  deployment?: string;
  stage?: string;
}
