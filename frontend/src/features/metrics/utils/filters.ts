import type { MetricsRange, MetricsScope, ProcessingFilters, UsageFilters } from "../types/filters";
const ranges: string[] = ["today", "7d", "30d", "90d", "custom"];
export function utcToday() {
  return new Date().toISOString().slice(0, 10);
}
export function validateDates(start: string, end: string, today = utcToday()): string | undefined {
  const valid = (value: string) =>
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) &&
    new Date(value).toISOString().slice(0, 10) === value;
  if (!valid(start) || !valid(end)) return "Enter valid start and end dates.";
  if (start > end) return "Start date must be on or before end date.";
  if (end > today) return "Dates cannot be in the future.";
  if ((Date.parse(end) - Date.parse(start)) / 86_400_000 >= 90) return "Choose at most 90 inclusive days.";
}
export function readFilters(params: URLSearchParams, scope: MetricsScope) {
  const rawRange = params.get("range") || "30d";
  const range = (ranges.includes(rawRange) ? rawRange : "30d") as MetricsRange;
  const dates = {
    ...scope,
    range,
    ...(range === "custom" ? { start: params.get("start") || "", end: params.get("end") || "" } : {}),
  };
  const status = params.get("status") || undefined;
  const processing: ProcessingFilters = {
    ...dates,
    document_type: params.get("document_type") || undefined,
    status: status === "succeeded" || status === "failed" ? status : undefined,
  };
  const usage: UsageFilters = {
    ...dates,
    provider: params.get("provider") || undefined,
    deployment: params.get("deployment") || undefined,
    stage: params.get("stage") || undefined,
  };
  const error = !ranges.includes(rawRange)
    ? "Choose a valid date range."
    : status && status !== "succeeded" && status !== "failed"
      ? "Choose a valid job status."
      : range === "custom"
        ? validateDates(dates.start || "", dates.end || "")
        : undefined;
  return { processing, usage, error };
}
export function updateFilters(params: URLSearchParams, changes: Record<string, string>) {
  const next = new URLSearchParams(params);
  Object.entries(changes).forEach(([key, value]) => (value ? next.set(key, value) : next.delete(key)));
  return next;
}
