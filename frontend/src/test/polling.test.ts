import {
  ACTIVE_DASHBOARD_POLL_MS,
  ACTIVE_RUN_LIST_POLL_MS,
  dashboardPollingInterval,
  IDLE_POLL_MS,
  runListPollingInterval,
} from "@/api/polling";

describe("adaptive polling", () => {
  it("checks the dashboard frequently only while a run is active", () => {
    expect(dashboardPollingInterval(undefined)).toBe(IDLE_POLL_MS);
    expect(dashboardPollingInterval({ runs: { succeeded: 8 } })).toBe(IDLE_POLL_MS);
    expect(dashboardPollingInterval({ runs: { queued: 1 } })).toBe(ACTIVE_DASHBOARD_POLL_MS);
    expect(dashboardPollingInterval({ runs: { running: 2 } })).toBe(ACTIVE_DASHBOARD_POLL_MS);
  });

  it("checks the run list frequently only while a listed run is active", () => {
    const page = (statuses: string[]) => ({ results: statuses.map((status) => ({ status })) });

    expect(runListPollingInterval(undefined)).toBe(IDLE_POLL_MS);
    expect(runListPollingInterval(page(["succeeded", "failed"]))).toBe(IDLE_POLL_MS);
    expect(runListPollingInterval(page(["succeeded", "running"]))).toBe(ACTIVE_RUN_LIST_POLL_MS);
    expect(runListPollingInterval(page(["queued"]))).toBe(ACTIVE_RUN_LIST_POLL_MS);
  });
});
