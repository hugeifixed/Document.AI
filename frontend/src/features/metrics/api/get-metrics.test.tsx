import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { get } from "@/common/api/client";
import { metrics } from "../testing/fixtures";
import { useMetrics } from "./get-metrics";
vi.mock("@/common/api/client", () => ({ get: vi.fn() }));
it("polls at 60 seconds only while visible and includes scope in cache identity", async () => {
  vi.useFakeTimers();
  focusManager.setFocused(true);
  vi.mocked(get).mockResolvedValue(metrics);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(({ project }) => useMetrics({ project, range: "30d" }), {
    wrapper,
    initialProps: { project: "first" },
  });
  try {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(get).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(get).toHaveBeenCalledTimes(2);
    focusManager.setFocused(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    expect(get).toHaveBeenCalledTimes(2);
    hook.rerender({ project: "second" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(get).toHaveBeenCalledTimes(3);
    expect(get).toHaveBeenLastCalledWith(
      "/metrics/",
      { project: "second", range: "30d" },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  } finally {
    hook.unmount();
    client.clear();
    focusManager.setFocused(undefined);
    vi.useRealTimers();
  }
});
