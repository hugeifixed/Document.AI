import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { Run } from "@/api/types";
import { RunDetail } from "@/pages/RunDetail";

const { getRun, listItems, postRun, successToast } = vi.hoisted(() => ({
  getRun: vi.fn(),
  listItems: vi.fn(),
  postRun: vi.fn(),
  successToast: vi.fn(),
}));

vi.mock("@/auth/Session", () => ({
  useSession: () => ({ user: { roles: ["docai_operators"] } }),
}));

vi.mock("sonner", () => ({
  toast: { success: successToast, error: vi.fn() },
}));

vi.mock("@/api/client", () => ({
  ApiError: class extends Error {
    code = "REQUEST_FAILED";
  },
  get: getRun,
  list: listItems,
  post: postRun,
}));

const runningRun: Run = {
  id: "run-1",
  project: "project-1",
  workflow: "workflow-1",
  workflow_name: "Extract invoices",
  workflow_type: "extract_structured",
  dataset: "dataset-1",
  dataset_name: "Invoices",
  name: "September run",
  status: "running",
  stage: "processing",
  total_items: 4,
  processed_items: 1,
  failed_items: 0,
  started_at: "2026-09-11T12:00:00Z",
  finished_at: null,
  cancel_requested: false,
  config_hash: "sha256:1234567890abcdef",
  prompt_versions: {},
  model_deployment: "",
  layout_adapter: "mock",
  llm_adapter: "mock",
  warnings: [],
  errors: [],
  created: "2026-09-11T12:00:00Z",
};

describe("RunDetail", () => {
  it("shows cooperative cancellation as soon as the API accepts it", async () => {
    getRun.mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith("/progress/")
          ? {
              total: 4,
              succeeded: 1,
              failed: 0,
              skipped: 2,
              queued: 0,
              running: 1,
              remaining: 1,
              stage: "cancelling",
              estimated_seconds_remaining: null,
            }
          : runningRun,
      ),
    );
    listItems.mockResolvedValue({ count: 0, page: 1, page_size: 200, total_pages: 0, results: [] });
    postRun.mockResolvedValue({ ...runningRun, cancel_requested: true, stage: "cancelling" });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/runs/run-1"]}>
          <Routes>
            <Route path="/runs/:id" element={<RunDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Cancel run" }));

    await waitFor(() => expect(postRun).toHaveBeenCalledWith("/runs/run-1/cancel/"));
    expect(await screen.findByRole("status")).toHaveTextContent("Cancellation requested");
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
    expect(successToast).toHaveBeenCalledWith("Cancellation requested");
  });
});
