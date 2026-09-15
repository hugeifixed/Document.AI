import { act, renderHook } from "@testing-library/react";
import { focusManager, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useRunLifecycle } from "@/runs/lifecycle";
import { createTestQueryClient } from "@/test/test-utils";
import { page, testRun, testRunItem } from "@/test/fixtures";

const { get, list } = vi.hoisted(() => ({ get: vi.fn(), list: vi.fn() }));
vi.mock("@/common/api/client", async (original) => ({ ...(await original<typeof import("@/common/api/client")>()), get, list }));

async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}
function setup() {
  let finished = false;
  let failedRefresh = false;
  let stamp = 0;
  get.mockImplementation((url: string) => {
    if (failedRefresh) return Promise.reject(new Error("Temporary interruption"));
    if (url.endsWith("/progress/"))
      return Promise.resolve({
        total: 4,
        succeeded: finished ? 4 : 1,
        failed: 0,
        skipped: 0,
        queued: 0,
        running: finished ? 0 : 3,
        remaining: finished ? 0 : 3,
        stage: finished ? "complete" : "processing",
        as_of: new Date(Date.parse("2026-09-13T12:00:00Z") + stamp++ * 3000).toISOString(),
        activity_items: [],
        last_milestone_at: null,
        estimated_finish_at: null,
        estimated_seconds_remaining: null,
      });
    return Promise.resolve(testRun({ status: finished ? "succeeded" : "queued" }));
  });
  list.mockImplementation(() =>
    failedRefresh
      ? Promise.reject(new Error("Temporary interruption"))
      : Promise.resolve(page([testRunItem({ status: finished ? "succeeded" : "queued" })])),
  );
  const client = createTestQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useRunLifecycle("run-1"), { wrapper });
  return {
    ...hook,
    finish: () => {
      finished = true;
    },
    interrupt: () => {
      failedRefresh = true;
    },
    restore: () => {
      failedRefresh = false;
    },
    client,
  };
}
beforeEach(() => {
  get.mockReset();
  list.mockReset();
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"] });
  focusManager.setFocused(true);
});
afterEach(() => {
  vi.useRealTimers();
  focusManager.setFocused(undefined);
});

it("polls queued work at three seconds, refreshes final totals and stops after completion", async () => {
  const hook = setup();
  await tick(10);
  expect(hook.result.current.progress.data?.succeeded).toBe(1);
  const initial = get.mock.calls.filter(([url]) => url.endsWith("/progress/")).length;
  await tick(3000);
  expect(get.mock.calls.filter(([url]) => url.endsWith("/progress/")).length).toBeGreaterThan(initial);
  hook.finish();
  await tick(3010);
  expect(hook.result.current.run.data?.status).toBe("succeeded");
  expect(hook.result.current.progress.data?.succeeded).toBe(4);
  expect(hook.result.current.items.data?.results[0].status).toBe("succeeded");
  const counts = [get.mock.calls.length, list.mock.calls.length];
  await tick(12_000);
  expect([get.mock.calls.length, list.mock.calls.length]).toEqual(counts);
});

it("retains data and the last successful clock receipt through transient refresh errors", async () => {
  const hook = setup();
  await tick(10);
  const receipt = hook.result.current.progressReceipt;
  hook.interrupt();
  await tick(3010);
  expect(hook.result.current.progress.isError).toBe(true);
  expect(hook.result.current.progress.data?.succeeded).toBe(1);
  expect(hook.result.current.items.data?.results).toHaveLength(1);
  expect(hook.result.current.run.data?.status).toBe("queued");
  expect(hook.result.current.progressReceipt).toEqual(receipt);
  hook.restore();
  await tick(3010);
  expect(hook.result.current.progress.isError).toBe(false);
  expect(hook.result.current.progressReceipt!.monotonicTime).toBeGreaterThan(receipt!.monotonicTime);
});

it("refreshes run, progress and items immediately when the window regains focus", async () => {
  setup();
  await tick(10);
  const before = [get.mock.calls.length, list.mock.calls.length];
  await act(async () => {
    focusManager.setFocused(false);
  });
  await act(async () => {
    focusManager.setFocused(true);
  });
  await tick(10);
  expect(get.mock.calls.length).toBeGreaterThanOrEqual(before[0] + 2);
  expect(list.mock.calls.length).toBeGreaterThan(before[1]);
});
