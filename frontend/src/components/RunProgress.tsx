import { CheckIcon, ExclamationTriangleIcon } from "@heroicons/react/20/solid";
import { useEffect, useRef } from "react";
import { announce } from "@/a11y/announce";
import type { ProcessingPhase, Progress, Run, RunItem } from "@/api/types";
import { FileNameLink } from "@/components/FileNameLink";
import { Card } from "@/components/ui";
import { isActiveRun } from "@/runs/lifecycle";
import {
  estimateLabel,
  MILESTONE_DELAY_MS,
  operationLabel,
  PHASE_LABELS,
  preparesScans,
  type ProgressReceipt,
  since,
  useProgressClock,
} from "@/runs/progress";

export const ITEM_FILTERS = [
  { value: "", label: "All" },
  { value: "succeeded,failed,skipped", label: "Completed" },
  { value: "succeeded", label: "Succeeded" },
  { value: "running", label: "Processing" },
  { value: "queued", label: "Queued" },
  { value: "failed", label: "Failed" },
  { value: "skipped", label: "Skipped" },
] as const;

function ActivityItem({ item, run, now }: { item: RunItem; run: Run; now: number | null }) {
  const snapshot = item.processing_progress;
  const operation = operationLabel(item);
  const lastOperation = useRef(operation);
  useEffect(() => {
    if (lastOperation.current !== operation) announce(`${item.document_name}: ${operation}.`);
    lastOperation.current = operation;
  }, [operation, item.document_name]);
  const elapsed = since(snapshot?.operation_started_at, now);
  const milestoneTime = item.progress_updated_at ? Date.parse(item.progress_updated_at) : NaN;
  const delayed = now !== null && Number.isFinite(milestoneTime) && now - milestoneTime >= MILESTONE_DELAY_MS;
  const phases: ProcessingPhase[] = [
    ...(preparesScans(run, item) ? ["preparing_scans" as const] : []),
    "reading_document",
    "analyzing",
    "saving_results",
  ];
  const counter = snapshot?.counter;
  return (
    <li className="min-w-0 py-4 first:pt-0 last:pb-0">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1 [&_a]:max-w-full">
          <FileNameLink name={item.document_name} to={`/documents/${item.document}?run=${run.id}&from=run`} />
          <p className="mt-2 text-sm">{operation}</p>
        </div>
        <span className="whitespace-nowrap text-caption text-secondary tabular-nums">
          {elapsed ? `${elapsed} elapsed` : "Elapsed unavailable"}
        </span>
      </div>
      {snapshot?.segment && (
        <p className="mt-2 text-caption text-secondary tabular-nums">
          Group {snapshot.segment.current.toLocaleString()} of {snapshot.segment.total.toLocaleString()}
        </p>
      )}
      {counter && (
        <p className="mt-2 text-caption tabular-nums">
          {counter.completed.toLocaleString()}/{counter.total.toLocaleString()}{" "}
          {counter.unit === "pages" ? "pages examined" : "chunks processed"}
          {snapshot?.segment ? " in this group" : ""}
        </p>
      )}
      {snapshot?.operation === "waiting_for_ocr" && (
        <p className="mt-2 text-caption text-secondary">
          Waiting for the document service; page completion is not reported.
        </p>
      )}
      {snapshot?.operation === "retry_wait" && snapshot.retry_at && (
        <p className="mt-2 text-caption text-secondary">
          {now !== null && Date.parse(snapshot.retry_at) > now
            ? `Retry scheduled in ${since(new Date(now).toISOString(), Date.parse(snapshot.retry_at))}`
            : "Scheduled retry is pending"}
        </p>
      )}
      {delayed && (
        <p className="mt-2 text-caption text-secondary">
          No new milestone for {since(item.progress_updated_at, now)} · {operation}
        </p>
      )}
      <details className="collapse collapse-arrow mt-2 min-w-0 overflow-visible border border-base-300 bg-base-100">
        <summary
          className="collapse-title min-h-11 p-2 pe-10 text-caption font-medium sm:min-h-10"
          aria-label={`Processing details for ${item.document_name}`}
        >
          Processing details
        </summary>
        <div className="collapse-content px-2">
          {snapshot ? (
            <ol className="grid gap-2 text-caption">
              {phases.map((phase) => {
                const complete = snapshot.completed_phases.includes(phase);
                const current = snapshot.phase === phase;
                return (
                  <li
                    key={phase}
                    className="flex items-center justify-between gap-4"
                    aria-current={current ? "step" : undefined}
                  >
                    <span>{PHASE_LABELS[phase]}</span>
                    <span
                      className={`inline-flex items-center gap-2 ${complete ? "text-success" : current ? "text-primary" : "text-secondary"}`}
                    >
                      {complete && <CheckIcon className="size-4" aria-hidden="true" />}
                      {complete ? "Complete" : current ? "Current" : "Pending"}
                    </span>
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className="text-caption text-secondary">Detailed milestones are unavailable for this document.</p>
          )}
        </div>
      </details>
    </li>
  );
}

export function RunProgress({
  run,
  progress,
  receipt,
  selectedFilter,
  onFilter,
  onRefresh,
  refreshing,
  error,
}: {
  run: Run;
  progress: Progress | undefined;
  receipt: ProgressReceipt | null;
  selectedFilter: string;
  onFilter: (status: string, focusTable?: boolean) => void;
  onRefresh: () => void;
  refreshing: boolean;
  error: boolean;
}) {
  const active = isActiveRun(run.status);
  const { now, interrupted } = useProgressClock(receipt, active);
  const total = progress?.total ?? run.total_items;
  const completed = progress ? progress.succeeded + progress.failed + progress.skipped : run.processed_items;
  const counts = [
    total,
    completed,
    progress?.succeeded ?? Math.max(0, run.processed_items - run.failed_items),
    progress?.running,
    progress?.queued,
    progress?.failed ?? run.failed_items,
    progress?.skipped,
  ];
  const activity = active
    ? (progress?.activity_items ?? []).filter((item) => ["running", "queued"].includes(item.status)).slice(0, 5)
    : [];
  const elapsed = since(
    run.started_at ?? run.created,
    active ? now : run.finished_at ? Date.parse(run.finished_at) : now,
  );
  const estimate = estimateLabel(run, progress, now, interrupted);
  const lastInterrupted = useRef(false);
  useEffect(() => {
    if (interrupted !== lastInterrupted.current)
      announce(interrupted ? "Progress updates interrupted." : "Progress updates restored.");
    lastInterrupted.current = interrupted;
  }, [interrupted]);
  return (
    <Card title={active ? "Run progress" : "Run summary"} className="mb-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-medium tabular-nums">
          {completed.toLocaleString()}/{total.toLocaleString()} documents completed
        </p>
        <p className="text-sm text-secondary tabular-nums">{elapsed ? `${elapsed} elapsed` : "Elapsed unavailable"}</p>
      </div>
      {active && (
        <progress
          className="progress progress-primary mt-2 w-full"
          value={completed}
          max={Math.max(total, 1)}
          aria-label="Completed documents"
        />
      )}
      {active && run.cancel_requested && (
        <output className="mt-4 block text-sm" aria-label="Cancellation requested">
          <strong className="block font-semibold">Cancellation requested</strong>
          <span className="text-secondary">
            Active documents will stop at a safe boundary. Documents that have not started are being skipped.
          </span>
        </output>
      )}
      {estimate && <p className="mt-2 text-caption text-secondary tabular-nums">{estimate}</p>}
      <fieldset className="mt-4 flex flex-wrap gap-2" aria-label="Filter documents by status">
        {ITEM_FILTERS.map((filter, index) => (
          <button
            key={filter.value}
            type="button"
            className={`btn btn-sm min-h-11 sm:min-h-10 ${selectedFilter === filter.value ? "btn-primary btn-soft" : "btn-ghost"}`}
            aria-pressed={selectedFilter === filter.value}
            onClick={() => onFilter(filter.value)}
          >
            {filter.label} <span className="tabular-nums">{counts[index]?.toLocaleString() ?? "—"}</span>
          </button>
        ))}
      </fieldset>
      {(interrupted || (!active && error)) && (
        <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
          <ExclamationTriangleIcon className="size-5 text-warning" aria-hidden="true" />
          <span>{interrupted ? "Updates interrupted" : "Progress summary could not be refreshed"}</span>
          <button
            type="button"
            className="btn btn-ghost btn-sm min-h-11 text-primary sm:min-h-10"
            onClick={onRefresh}
            disabled={refreshing && !interrupted}
          >
            Retry refresh
          </button>
        </div>
      )}
      {active && (
        <div className="mt-4 border-t border-base-300 pt-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">Current activity</h3>
            <button
              type="button"
              className="btn btn-ghost btn-sm min-h-11 text-primary sm:min-h-10"
              onClick={() => onFilter("running,queued", true)}
            >
              View all active documents
            </button>
          </div>
          {activity.length > 0 ? (
            <ul className="divide-y divide-base-300">
              {activity.map((item) => (
                <ActivityItem key={item.id} item={item} run={run} now={now} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-secondary">
              {run.status === "queued" || (progress?.queued && !progress.running)
                ? "Waiting for a worker (busy or unavailable)"
                : "Waiting for the next progress update"}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
