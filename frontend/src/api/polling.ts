import type { Dashboard, Run } from "./types";

export const ACTIVE_DASHBOARD_POLL_MS = 15_000;
export const ACTIVE_RUN_LIST_POLL_MS = 10_000;
export const IDLE_POLL_MS = 60_000;

const ACTIVE_RUN_STATUSES = new Set(["queued", "running"]);

export function dashboardPollingInterval(data: { runs: Dashboard["runs"] } | undefined) {
  const hasActiveRuns = (data?.runs.queued ?? 0) + (data?.runs.running ?? 0) > 0;
  return hasActiveRuns ? ACTIVE_DASHBOARD_POLL_MS : IDLE_POLL_MS;
}

export function runListPollingInterval(data: { results: Array<Pick<Run, "status">> } | undefined) {
  return data?.results.some((run) => ACTIVE_RUN_STATUSES.has(run.status)) ? ACTIVE_RUN_LIST_POLL_MS : IDLE_POLL_MS;
}
