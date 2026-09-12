import { screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import type { LLMUsageSummary, Run } from "@/api/types";
import { RunDetail } from "@/pages/RunDetail";
import { createTestQueryClient, renderWithApp } from "@/test/test-utils";

const { getRun, listItems, postRun, session, successToast } = vi.hoisted(() => ({
  getRun: vi.fn(),
  listItems: vi.fn(),
  postRun: vi.fn(),
  session: { roles: ["docai_operators"] as string[] },
  successToast: vi.fn(),
}));

vi.mock("@/auth/Session", () => ({
  useSession: () => ({ user: { roles: session.roles } }),
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
  workflow_version: 1,
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

const usageSummary: LLMUsageSummary = {
  run: "run-1",
  calls: 2,
  measured_calls: 2,
  input_tokens: 1_000,
  cached_input_tokens: 200,
  output_tokens: 234,
  reasoning_tokens: 34,
  total_tokens: 1_234,
  finish_reasons: { stop: 2 },
  safety_outcomes: { clear: 2 },
  by_stage: [
    {
      stage: "extraction",
      calls: 2,
      measured_calls: 2,
      input_tokens: 1_000,
      cached_input_tokens: 200,
      output_tokens: 234,
      reasoning_tokens: 34,
      total_tokens: 1_234,
    },
  ],
  by_item: [
    {
      run_item: "item-1",
      document: "document-1",
      document_name: "damaged-statement.pdf",
      calls: 2,
      measured_calls: 2,
      input_tokens: 1_000,
      cached_input_tokens: 200,
      output_tokens: 234,
      reasoning_tokens: 34,
      total_tokens: 1_234,
    },
  ],
};

describe("RunDetail", () => {
  beforeEach(() => {
    getRun.mockReset();
    listItems.mockReset();
    postRun.mockReset();
    successToast.mockReset();
    session.roles = ["docai_operators"];
  });

  it("shows cooperative cancellation as soon as the API accepts it", async () => {
    getRun.mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith("/usage/")
          ? usageSummary
          : url.endsWith("/progress/")
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
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(["runs", "project-1"], { results: [runningRun] });
    queryClient.setQueryData(["dashboard", "project-1"], { runs: { running: 1 } });
    const { user } = renderWithApp(
      <Routes>
        <Route path="/runs/:id" element={<RunDetail />} />
      </Routes>,
      { route: "/runs/run-1", queryClient },
    );

    await user.click(await screen.findByRole("button", { name: "Cancel run" }));

    await waitFor(() => expect(postRun).toHaveBeenCalledWith("/runs/run-1/cancel/"));
    expect(await screen.findByRole("status")).toHaveTextContent("Cancellation requested");
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
    expect(successToast).toHaveBeenCalledWith("Cancellation requested");
    expect(queryClient.getQueryState(["runs", "project-1"])?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(["dashboard", "project-1"])?.isInvalidated).toBe(true);
  });

  it("shows document failures and evaluation metrics, then retries failed items", async () => {
    const completedRun: Run = {
      ...runningRun,
      status: "partial",
      stage: "complete",
      processed_items: 1,
      failed_items: 1,
      finished_at: "2026-09-11T12:05:00Z",
      prompt_versions: { extraction: { name: "statement-fields", version: 3 } },
      warnings: ["One page had low OCR confidence"],
      metrics: {
        documents: 2,
        processed: 1,
        failed: 1,
        has_ground_truth: true,
        extraction: {
          aggregate: {
            support: 2,
            match: 1,
            mismatch: 1,
            missing: 0,
            spurious: 0,
            true_blank: 0,
            accuracy: 0.5,
            precision: 0.5,
            recall: 1,
            specificity: null,
            npv: null,
            f1: 0.67,
            missing_rate: 0,
            hallucinated_rate: 0,
          },
          per_field: {
            account_holder: {
              support: 2,
              match: 1,
              mismatch: 1,
              missing: 0,
              spurious: 0,
              true_blank: 0,
              accuracy: 0.5,
              precision: 0.5,
              recall: 1,
              specificity: null,
              npv: null,
              f1: 0.67,
              missing_rate: 0,
              hallucinated_rate: 0,
            },
          },
          out_of_schema_labels: { legacy_code: 1 },
        },
        classification: {
          labels: ["statement", "other"],
          matrix: [
            [1, 0],
            [1, 0],
          ],
          accuracy: 0.5,
          macro: { f1: 0.33 },
          micro: { f1: 0.5 },
          weighted: { f1: 0.33 },
          other_or_unclassified_rate: 0.5,
          per_class: {},
        },
        segmentation: {
          aggregate: { boundary_f1: 0.8, document_count: 2 },
          per_document: [],
        },
        quality_indicators: {
          kind: "quality",
          note: "Operational indicators only.",
          document_count: 2,
          per_field: {
            account_holder: {
              non_blank_rate: 1,
              low_score_rate: 0.5,
              grounding_rate: 0.5,
              validation_failure_rate: 0,
            },
          },
        },
      },
    };
    getRun.mockImplementation((url: string) => Promise.resolve(url.endsWith("/usage/") ? usageSummary : completedRun));
    listItems.mockResolvedValue({
      count: 1,
      page: 1,
      page_size: 200,
      total_pages: 1,
      results: [
        {
          id: "item-1",
          document: "document-1",
          document_name: "damaged-statement.pdf",
          status: "failed",
          error_code: "LAYOUT_FAILED",
          error_message: "The document service timed out",
          attempts: 2,
          retryable: true,
          duration_ms: 1250,
        },
      ],
    });
    postRun.mockResolvedValue(completedRun);
    const { user } = renderWithApp(
      <Routes>
        <Route path="/runs/:id" element={<RunDetail />} />
      </Routes>,
      { route: "/runs/run-1" },
    );

    expect(await screen.findByText("The document service timed out")).toBeInTheDocument();
    expect(screen.getByText("One page had low OCR confidence")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Extraction metrics per field" })).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: "Confusion matrix: rows are truth, columns are predictions" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Operational indicators only.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "LLM token usage" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "LLM token usage by workflow stage" })).toBeInTheDocument();
    expect(screen.getByText("stop 2")).toBeInTheDocument();
    expect(screen.getByText("clear 2")).toBeInTheDocument();
    expect(screen.getAllByText("1,234")).toHaveLength(3);

    await user.click(screen.getByRole("button", { name: "Retry 1 failed" }));
    await waitFor(() => expect(postRun).toHaveBeenCalledWith("/runs/run-1/retry/"));
    expect(successToast).toHaveBeenCalledWith("Run retry requested");
  });

  it("does not request or display operational usage for a viewer", async () => {
    session.roles = ["docai_viewers"];
    getRun.mockResolvedValue(runningRun);
    listItems.mockResolvedValue({ count: 0, page: 1, page_size: 200, total_pages: 0, results: [] });

    renderWithApp(
      <Routes>
        <Route path="/runs/:id" element={<RunDetail />} />
      </Routes>,
      { route: "/runs/run-1" },
    );

    expect(await screen.findByRole("heading", { name: "September run" })).toBeInTheDocument();
    expect(getRun.mock.calls.some(([url]) => String(url).endsWith("/usage/"))).toBe(false);
    expect(screen.queryByRole("heading", { name: "LLM token usage" })).not.toBeInTheDocument();
  });
});
