import {
  ACTIVE_DASHBOARD_POLL_MS,
  ACTIVE_RUN_DETAIL_POLL_MS,
  ACTIVE_RUN_LIST_POLL_MS,
  dashboardPollingInterval,
  IDLE_POLL_MS,
  isActiveRun,
  isTerminalRun,
  runActionsFor,
  runItemPollingInterval,
  runListPollingInterval,
} from "@/runs/lifecycle";

describe("adaptive polling", () => {
  it("checks the dashboard frequently only while a run is active", () => {
    expect(dashboardPollingInterval(undefined)).toBe(IDLE_POLL_MS);
    expect(dashboardPollingInterval({ runs: { succeeded: 8 } })).toBe(IDLE_POLL_MS);
    expect(dashboardPollingInterval({ runs: { queued: 1 } })).toBe(ACTIVE_DASHBOARD_POLL_MS);
    expect(dashboardPollingInterval({ runs: { running: 2 } })).toBe(ACTIVE_DASHBOARD_POLL_MS);
  });

  it("checks the run list frequently only while a listed run is active", () => {
    const page = (statuses: Array<"queued" | "running" | "succeeded" | "failed">) => ({
      results: statuses.map((status) => ({ status })),
    });

    expect(runListPollingInterval(undefined)).toBe(IDLE_POLL_MS);
    expect(runListPollingInterval(page(["succeeded", "failed"]))).toBe(IDLE_POLL_MS);
    expect(runListPollingInterval(page(["succeeded", "running"]))).toBe(ACTIVE_RUN_LIST_POLL_MS);
    expect(runListPollingInterval(page(["queued"]))).toBe(ACTIVE_RUN_LIST_POLL_MS);
  });

  it("keeps run items fresh through the final status transition", () => {
    const items = (statuses: Array<"queued" | "running" | "succeeded" | "failed" | "skipped">) => ({
      results: statuses.map((status) => ({ status })),
    });

    expect(runItemPollingInterval({ status: "running" }, items(["succeeded"]))).toBe(ACTIVE_RUN_DETAIL_POLL_MS);
    expect(runItemPollingInterval({ status: "partial" }, items(["running", "succeeded"]))).toBe(
      ACTIVE_RUN_DETAIL_POLL_MS,
    );
    expect(runItemPollingInterval({ status: "partial" }, items(["failed", "succeeded"]))).toBe(false);
  });

  it("keeps lifecycle actions consistent with backend run states", () => {
    expect(isActiveRun("queued")).toBe(true);
    expect(isTerminalRun("partial")).toBe(true);
    expect(runActionsFor({ status: "running", cancel_requested: false }, 1)).toEqual({
      canCancel: true,
      cancellationPending: false,
      canRetry: false,
    });
    expect(runActionsFor({ status: "partial", cancel_requested: false }, 1).canRetry).toBe(true);
    expect(runActionsFor({ status: "running", cancel_requested: true }, 0).cancellationPending).toBe(true);
  });
});
