import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, list, post, tableParams } from "@/api/client";
import type { Dashboard, LLMUsageSummary, Page, Progress, Run, RunItem, RunStatus } from "@/api/types";
import type { TableState } from "@/hooks/useTableState";
import type { ProgressReceipt } from "./progress";

export const RUN_STATUSES: readonly RunStatus[] = ["queued", "running", "succeeded", "partial", "failed", "cancelled"];
export const ACTIVE_DASHBOARD_POLL_MS = 15_000;
export const ACTIVE_RUN_LIST_POLL_MS = 10_000;
export const IDLE_POLL_MS = 60_000;
export const ACTIVE_RUN_DETAIL_POLL_MS = 3_000;

const ACTIVE_RUN_STATUSES = new Set<RunStatus>(["queued", "running"]);
const TERMINAL_RUN_STATUSES = new Set<RunStatus>(["succeeded", "failed", "cancelled", "partial"]);

export function isActiveRun(status: RunStatus) {
  return ACTIVE_RUN_STATUSES.has(status);
}

export function isTerminalRun(status: RunStatus) {
  return TERMINAL_RUN_STATUSES.has(status);
}

export function runActionsFor(run: Pick<Run, "status" | "cancel_requested">, failedItems = 0) {
  return {
    canCancel: isActiveRun(run.status) && !run.cancel_requested,
    cancellationPending: isActiveRun(run.status) && run.cancel_requested,
    canRetry: isTerminalRun(run.status) && failedItems > 0,
  };
}

export function dashboardPollingInterval(data: { runs: Dashboard["runs"] } | undefined) {
  const hasActiveRuns = (data?.runs.queued ?? 0) + (data?.runs.running ?? 0) > 0;
  return hasActiveRuns ? ACTIVE_DASHBOARD_POLL_MS : IDLE_POLL_MS;
}

export function runListPollingInterval(data: { results: Array<Pick<Run, "status">> } | undefined) {
  return data?.results.some((run) => isActiveRun(run.status)) ? ACTIVE_RUN_LIST_POLL_MS : IDLE_POLL_MS;
}

export function runItemPollingInterval(
  run: Pick<Run, "status"> | undefined,
  data: { results: Array<Pick<RunItem, "status">> } | undefined,
) {
  const hasActiveItems = data?.results.some((item) => item.status === "queued" || item.status === "running") ?? false;
  return (run && isActiveRun(run.status)) || hasActiveItems ? ACTIVE_RUN_DETAIL_POLL_MS : false;
}

type RunCollectionScope =
  | { purpose: "manage"; projectId: string | null; datasetId: string | null; table: TableState }
  | { purpose: "results"; projectId: string | null; datasetId: string | null }
  | { purpose: "evaluation"; projectId: string | null; datasetId?: string | null }
  | { purpose: "export"; projectId: string | null; datasetId?: string | null }
  | { purpose: "review"; datasetId: string | undefined; documentId: string | undefined };

function collectionRequest(scope: RunCollectionScope) {
  switch (scope.purpose) {
    case "manage":
      return {
        queryKey: ["runs", scope.projectId, scope.datasetId, scope.table] as const,
        params: {
          ...tableParams(scope.table),
          ...(scope.projectId ? { project: scope.projectId } : {}),
          ...(scope.datasetId ? { dataset: scope.datasetId } : {}),
        },
        enabled: true,
        poll: true,
      };
    case "results":
      return {
        queryKey: ["runs", scope.projectId, scope.datasetId, "recent"] as const,
        params: {
          page_size: 50,
          ...(scope.projectId ? { project: scope.projectId } : {}),
          ...(scope.datasetId ? { dataset: scope.datasetId } : {}),
        },
        enabled: true,
        poll: false,
      };
    case "evaluation":
      return {
        queryKey: ["runs", scope.projectId, scope.datasetId ?? null, "done"] as const,
        params: {
          page_size: 100,
          status__in: "succeeded,partial",
          ...(scope.projectId ? { project: scope.projectId } : {}),
          ...(scope.datasetId ? { dataset: scope.datasetId } : {}),
        },
        enabled: true,
        poll: false,
      };
    case "export":
      return {
        queryKey: ["runs", scope.projectId, scope.datasetId ?? null, "export"] as const,
        params: {
          page_size: 50,
          status__in: "succeeded,partial,failed,cancelled",
          ...(scope.projectId ? { project: scope.projectId } : {}),
          ...(scope.datasetId ? { dataset: scope.datasetId } : {}),
        },
        enabled: true,
        poll: false,
      };
    case "review":
      return {
        queryKey: ["runs", "document", scope.documentId] as const,
        params: {
          page_size: 200,
          ordering: "-created",
          dataset: scope.datasetId,
          document: scope.documentId,
        },
        enabled: !!scope.datasetId && !!scope.documentId,
        poll: false,
      };
  }
}

/** Purpose-specific Run collection queries keep filters, identity, and polling together. */
export function useRunCollection(scope: RunCollectionScope) {
  const request = collectionRequest(scope);
  return useQuery({
    queryKey: request.queryKey,
    queryFn: ({ signal }) => list<Run>("/runs/", request.params, { signal }),
    enabled: request.enabled,
    refetchInterval: request.poll
      ? (query) => runListPollingInterval(query.state.data as Page<Run> | undefined)
      : false,
  });
}

export type RunAction = "cancel" | "retry" | "execute";

export interface CreateRunInput {
  project: string | null;
  workflow: string;
  dataset: string;
  name: string;
  sample_size?: number;
  document_ids?: string[];
  execute: true;
}

export function useCreateRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateRunInput) => post<Run>("/runs/", input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

/** One controller for Run detail, progress, items, and lifecycle actions. */
export function useRunLifecycle(runId: string | undefined, includeUsage = false, itemTable?: TableState) {
  const queryClient = useQueryClient();
  const previousRunStatus = useRef<{ id: string; status: RunStatus } | undefined>(undefined);
  const [receipt, setReceipt] = useState<(ProgressReceipt & { runId: string | undefined }) | null>(null);
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: ({ signal }) => get<Run>(`/runs/${runId}/`, undefined, { signal }),
    enabled: !!runId,
    refetchOnWindowFocus: "always",
    refetchInterval: (query) =>
      query.state.data && isActiveRun(query.state.data.status) ? ACTIVE_RUN_DETAIL_POLL_MS : false,
  });
  const progress = useQuery({
    queryKey: ["progress", runId],
    queryFn: async ({ signal }) => {
      const result = await get<Progress>(`/runs/${runId}/progress/`, undefined, { signal });
      setReceipt({ runId, serverTime: Date.parse(result.as_of), monotonicTime: performance.now() });
      return result;
    },
    refetchInterval: run.data && isActiveRun(run.data.status) ? ACTIVE_RUN_DETAIL_POLL_MS : false,
    refetchOnWindowFocus: "always",
    enabled: !!runId && !!run.data,
  });
  const items = useQuery({
    queryKey: ["run-items", runId, itemTable],
    queryFn: ({ signal }) =>
      list<RunItem>(
        "/run-items/",
        {
          run: runId,
          page_size: 50,
          ordering: "created",
          ...(itemTable ? tableParams(itemTable) : {}),
        },
        { signal },
      ),
    enabled: !!runId,
    refetchInterval: (query) => runItemPollingInterval(run.data, query.state.data),
    refetchOnWindowFocus: "always",
  });
  const usage = useQuery({
    queryKey: ["run-usage", runId],
    queryFn: ({ signal }) => get<LLMUsageSummary>(`/runs/${runId}/usage/`, undefined, { signal }),
    enabled: !!runId && includeUsage,
    refetchInterval: run.data && isActiveRun(run.data.status) ? ACTIVE_RUN_DETAIL_POLL_MS : false,
  });
  useEffect(() => {
    const currentStatus = run.data?.status;
    if (
      runId &&
      currentStatus &&
      previousRunStatus.current &&
      previousRunStatus.current.id === runId &&
      isActiveRun(previousRunStatus.current.status) &&
      isTerminalRun(currentStatus)
    ) {
      void queryClient.invalidateQueries({ queryKey: ["run-items", runId] });
      void queryClient.invalidateQueries({ queryKey: ["run-usage", runId] });
      void queryClient.invalidateQueries({ queryKey: ["progress", runId] });
    }
    previousRunStatus.current = runId && currentStatus ? { id: runId, status: currentStatus } : undefined;
  }, [queryClient, run.data?.status, runId]);
  const action = useMutation({
    mutationFn: (requested: RunAction) => post<Run>(`/runs/${runId}/${requested}/`),
    onSuccess: (updated) => {
      queryClient.setQueryData(["run", runId], updated);
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
      void queryClient.invalidateQueries({ queryKey: ["run-items", runId] });
      void queryClient.invalidateQueries({ queryKey: ["run-usage", runId] });
      void queryClient.invalidateQueries({ queryKey: ["progress", runId] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  return { run, progress, items, usage, action, progressReceipt: receipt?.runId === runId ? receipt : null };
}
