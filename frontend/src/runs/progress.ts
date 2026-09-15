import { useEffect, useState } from "react";
import type { ProcessingOperation, ProcessingPhase, Progress, Run, RunItem } from "@/common/types/api";
import { isActiveRun } from "./lifecycle";

export interface ProgressReceipt {
  serverTime: number;
  monotonicTime: number;
}
export const INTERRUPTED_AFTER_MS = 15_000;
export const MILESTONE_DELAY_MS = 120_000;

/** Advance the server timestamp using monotonic client time, never the browser wall clock. */
export function progressTime(receipt: ProgressReceipt | null, monotonicNow: number): number | null {
  return receipt && Number.isFinite(receipt.serverTime)
    ? receipt.serverTime + Math.max(0, monotonicNow - receipt.monotonicTime)
    : null;
}

export function useProgressClock(receipt: ProgressReceipt | null, active: boolean) {
  const [mountedAt] = useState(() => performance.now());
  const [tick, setTick] = useState(() => performance.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setTick(performance.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [active]);
  const monotonicNow = Math.max(tick, receipt?.monotonicTime ?? mountedAt);
  return {
    now: progressTime(receipt, monotonicNow),
    interrupted: active && monotonicNow - (receipt?.monotonicTime ?? mountedAt) >= INTERRUPTED_AFTER_MS,
  };
}

export function humanDuration(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1_000));
  if (seconds < 60) return `${seconds.toLocaleString()}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes.toLocaleString()}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60).toLocaleString()}h ${minutes % 60}m`;
}

export function since(timestamp: string | null | undefined, now: number | null): string | null {
  const start = timestamp ? Date.parse(timestamp) : NaN;
  return now !== null && Number.isFinite(start) ? humanDuration(now - start) : null;
}

export const OPERATION_LABELS: Record<ProcessingOperation, string> = {
  queued: "Waiting for a worker (busy or unavailable)",
  preparing_scans: "Preparing scans",
  reading_document: "Reading document",
  waiting_for_ocr: "Waiting for document recognition",
  reusing_layout: "Reusing saved document layout",
  identifying_groups: "Identifying and classifying document groups",
  classifying: "Classifying document",
  extracting: "Extracting fields",
  checking_evidence: "Checking evidence",
  saving_results: "Saving results",
  retry_wait: "Waiting to retry",
  complete: "Complete",
  failed: "Failed",
  cancelled: "Cancelled",
};
export const PHASE_LABELS: Partial<Record<ProcessingPhase, string>> = {
  preparing_scans: "Prepare scans",
  reading_document: "Read document",
  analyzing: "Analyze",
  saving_results: "Save results",
};

export function operationLabel(item: RunItem): string {
  if (item.processing_progress) return OPERATION_LABELS[item.processing_progress.operation] ?? "Processing document";
  if (item.status === "queued") return OPERATION_LABELS.queued;
  if (item.status !== "running")
    return item.status === "succeeded" ? "Complete" : item.status === "skipped" ? "Skipped" : "Failed";
  return item.stage === "normalization"
    ? "Preparing scans"
    : item.stage === "layout"
      ? "Reading document"
      : "Processing document";
}

export function preparesScans(run: Run, item: RunItem): boolean {
  const config = run.config_snapshot?.config as { input_quality?: { mode?: string } } | undefined;
  const quality = config?.input_quality;
  return (
    quality?.mode === "adaptive" ||
    item.input_quality?.mode === "adaptive" ||
    item.processing_progress?.phase === "preparing_scans" ||
    !!item.processing_progress?.completed_phases.includes("preparing_scans")
  );
}

/** ETA eligibility remains authoritative on the server; these guards also hide outdated estimates. */
export function estimateLabel(
  run: Run,
  progress: Progress | undefined,
  now: number | null,
  interrupted: boolean,
): string | null {
  if (
    !progress ||
    !isActiveRun(run.status) ||
    run.cancel_requested ||
    interrupted ||
    progress.failed ||
    progress.skipped ||
    progress.activity_items?.some((item) => item.attempts > 1 || item.processing_progress?.operation === "retry_wait")
  )
    return null;
  if (progress.remaining <= 0 || progress.total < 4) return null;
  if (!progress.estimated_finish_at || progress.succeeded < 3 || now === null)
    return progress.succeeded < 3 ? "Estimating after more documents finish" : null;
  const remaining = Date.parse(progress.estimated_finish_at) - now;
  if (!Number.isFinite(remaining)) return null;
  if (remaining <= 0) return "Taking longer than the estimate";
  return `About ${humanDuration(remaining)} remaining`;
}
