import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { ApiError, get } from "@/common/api/client";
import { metrics, usage } from "../testing/fixtures";
import { MetricsDashboard } from "./metrics-dashboard";
vi.mock("@/common/api/client", async (original) => ({
  ...(await original<typeof import("@/common/api/client")>()),
  get: vi.fn(),
}));
function mount(canViewUsage = false, initial = "/metrics") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [{ path: "/metrics", element: <MetricsDashboard projectId="p" datasetId="d" canViewUsage={canViewUsage} /> }],
    { initialEntries: [initial] },
  );
  const view = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...view, router, client };
}
beforeEach(() => {
  vi.mocked(get).mockReset();
  vi.mocked(get).mockImplementation(async (url) => (url === "/metrics/usage/" ? usage : metrics));
});
it("loads scoped metrics and never requests restricted usage for readers", async () => {
  mount();
  await screen.findByText("Completed jobs");
  expect(get).toHaveBeenCalledWith(
    "/metrics/",
    expect.objectContaining({ project: "p", dataset: "d", range: "30d" }),
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  );
  expect(screen.queryByRole("heading", { name: "LLM usage" })).not.toBeInTheDocument();
  expect(vi.mocked(get).mock.calls.every(([url]) => url !== "/metrics/usage/")).toBe(true);
});
it("isolates processing and usage requests and restores URL history", async () => {
  const { router } = mount(true);
  await screen.findByText("Completed jobs");
  await screen.findByRole("combobox", { name: "Provider" });
  vi.mocked(get).mockClear();
  fireEvent.change(screen.getByRole("combobox", { name: "Job status" }), { target: { value: "failed" } });
  await waitFor(() => expect(router.state.location.search).toContain("status=failed"));
  await screen.findByRole("combobox", { name: "Job status" });
  expect(vi.mocked(get).mock.calls.map(([url]) => url)).toEqual(["/metrics/"]);
  vi.mocked(get).mockClear();
  fireEvent.change(screen.getByRole("combobox", { name: "Provider" }), { target: { value: "azure" } });
  await waitFor(() => expect(router.state.location.search).toContain("provider=azure"));
  await screen.findByRole("combobox", { name: "Provider" });
  expect(vi.mocked(get).mock.calls.map(([url]) => url)).toEqual(["/metrics/usage/"]);
  await act(() => router.navigate(-1));
  expect(screen.getByRole("combobox", { name: "Provider" })).toHaveValue("");
  expect(screen.getByRole("combobox", { name: "Job status" })).toHaveValue("failed");
});
it("removes old-filter data while loading and aborts obsolete requests", async () => {
  const { router } = mount();
  await screen.findByText("Completed jobs");
  let resolve: (value: unknown) => void = () => {};
  vi.mocked(get).mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Job status" }), { target: { value: "failed" } });
  expect(await screen.findByRole("status", { name: "Loading metrics" })).toBeVisible();
  expect(screen.queryByText("Completed jobs")).not.toBeInTheDocument();
  const last = vi.mocked(get).mock.calls.at(-1)!;
  const signal = last[2]!.signal!;
  await act(() => router.navigate("/metrics?status=succeeded"));
  expect(signal.aborted).toBe(true);
  await screen.findByText("Completed jobs");
  await act(async () => resolve({ ...metrics, processing: { ...metrics.processing, completed_jobs: 9999 } }));
  expect(screen.queryByText("9,999")).not.toBeInTheDocument();
});
it("blocks invalid custom dates and shows API errors with retry", async () => {
  const view = mount(false, "/metrics?range=custom&start=2026-02-30&end=2026-03-01");
  expect(await screen.findByRole("alert")).toHaveTextContent("valid");
  expect(get).not.toHaveBeenCalled();
  view.unmount();
  vi.mocked(get).mockRejectedValueOnce(
    new ApiError(500, { message: "Unavailable", error_code: "METRICS_FAILED", trace_id: "trace-1" }),
  );
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("METRICS_FAILED");
  fireEvent.click(screen.getByRole("button", { name: "Retry metrics" }));
  await screen.findByText("Completed jobs");
});
it("handles denied overview and denied usage without leaking cached content", async () => {
  vi.mocked(get).mockImplementation(async (url) => {
    if (url === "/metrics/usage/") throw new ApiError(403, { message: "Usage denied" });
    return metrics;
  });
  mount(true);
  await screen.findByText("Completed jobs");
  expect(await screen.findByRole("alert")).toHaveTextContent("Usage denied");
  expect(screen.queryByText("Measured tokens")).not.toBeInTheDocument();
});

it("shows a denied whole-page state and exposes no operational data", async () => {
  vi.mocked(get).mockRejectedValue(new ApiError(403, { message: "Access denied" }));
  mount();
  expect(await screen.findByRole("heading", { name: "Access denied" })).toBeVisible();
  expect(screen.queryByText("Completed jobs")).not.toBeInTheDocument();
});
it("manual refresh updates both permitted sections", async () => {
  mount(true);
  await screen.findByText("Completed jobs");
  await screen.findByRole("combobox", { name: "Provider" });
  vi.mocked(get).mockClear();
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  expect(
    vi
      .mocked(get)
      .mock.calls.map(([url]) => url)
      .sort(),
  ).toEqual(["/metrics/", "/metrics/usage/"]);
});

it.each(["Document type", "Job status", "Provider", "Deployment", "Stage"])(
  "keeps %s mounted and focused through an uncached request",
  async (name) => {
    mount(true);
    await screen.findByText("Completed jobs");
    await screen.findByText("Recorded responses");
    const control = screen.getByRole("combobox", { name });
    const value = (control as HTMLSelectElement).options[1].value;
    let resolve: (data: unknown) => void = () => {};
    vi.mocked(get).mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    act(() => control.focus());
    fireEvent.change(control, { target: { value } });
    const isUsage = ["Provider", "Deployment", "Stage"].includes(name);
    await screen.findByRole("status", { name: isUsage ? "Loading LLM usage" : "Loading metrics" });
    expect(screen.getByRole("combobox", { name })).toBe(control);
    expect(control).toHaveFocus();
    expect(control).toHaveValue(value);
    expect(screen.queryByText(isUsage ? "Recorded responses" : "Completed jobs")).not.toBeInTheDocument();
    await act(async () => resolve(isUsage ? usage : metrics));
    await screen.findByText(isUsage ? "Recorded responses" : "Completed jobs");
    expect(control).toHaveFocus();
  },
);
