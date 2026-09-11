import { within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import type { Dataset, Page } from "@/api/types";
import { Configurations } from "@/pages/Configurations";
import { Datasets } from "@/pages/Datasets";
import { EvaluationPage } from "@/pages/Evaluation";
import { Runs } from "@/pages/Runs";
import {
  page,
  testDashboard,
  testDataset,
  testDocument,
  testEvaluation,
  testRun,
  testWorkflow,
} from "@/test/fixtures";
import { renderWithApp, screen, waitFor } from "@/test/test-utils";

const controls = vi.hoisted(() => ({
  get: vi.fn(),
  list: vi.fn(),
  post: vi.fn(),
  successToast: vi.fn(),
  preferences: { pageSize: 25 },
  workingContext: {
    projectId: "project-1" as string | null,
    datasetId: "dataset-1" as string | null,
    selectDatasetForProject: vi.fn(),
  },
  roles: ["docai_operators", "docai_reviewers", "docai_approvers"] as string[],
}));

vi.mock("@/auth/Session", () => ({
  useSession: () => ({ user: { roles: controls.roles } }),
}));
vi.mock("@/store/prefs", () => {
  const usePrefs = Object.assign(
    (selector?: (state: typeof controls.preferences) => unknown) =>
      selector ? selector(controls.preferences) : controls.preferences,
    { getState: () => controls.preferences },
  );
  return { usePrefs };
});
vi.mock("@/workspace/context", () => {
  const useWorkingContext = Object.assign(
    (selector?: (state: typeof controls.workingContext) => unknown) =>
      selector ? selector(controls.workingContext) : controls.workingContext,
    { getState: () => controls.workingContext },
  );
  return { useWorkingContext };
});
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  get: controls.get,
  list: controls.list,
  post: controls.post,
}));
vi.mock("sonner", () => ({ toast: { success: controls.successToast, error: vi.fn() } }));

describe("critical page workflows", () => {
  beforeEach(() => {
    controls.list.mockReset();
    controls.get.mockReset().mockImplementation((url: string) =>
      Promise.resolve(url === "/dashboard/" ? testDashboard() : testRun({ status: "succeeded" })),
    );
    controls.post.mockReset();
    controls.successToast.mockReset();
    controls.workingContext.projectId = "project-1";
    controls.workingContext.datasetId = "dataset-1";
    controls.workingContext.selectDatasetForProject.mockReset();
    controls.roles = ["docai_operators", "docai_reviewers", "docai_approvers"];
  });

  it("creates a dataset and selects it as the active working context", async () => {
    const activeDataset = testDataset();
    const createdDataset = testDataset({ id: "dataset-2", name: "Production statements", is_production: true });
    let datasetCreated = false;
    const failedDocument = testDocument({
      original_filename: "quarterly-statement.pdf",
      file_format: "pdf",
      status: "failed",
      validation_errors: [{ code: "PASSWORD_PROTECTED", message: "Remove the PDF password" }],
    });
    controls.list.mockImplementation((url: string) => {
      if (url === "/datasets/") {
        return Promise.resolve(page(datasetCreated ? [activeDataset, createdDataset] : [activeDataset]));
      }
      if (url === "/documents/") return Promise.resolve(page([failedDocument]));
      return Promise.resolve(page([]));
    });
    controls.post.mockImplementation(async () => {
      datasetCreated = true;
      return createdDataset;
    });
    const { queryClient, user } = renderWithApp(<Datasets />);
    let cachedDatasetIdsWhenSelected: string[] | undefined;
    controls.workingContext.selectDatasetForProject.mockImplementation(() => {
      cachedDatasetIdsWhenSelected = queryClient
        .getQueryData<Page<Dataset>>(["datasets", "project-1"])
        ?.results.map(({ id }) => id);
    });

    expect(await screen.findByRole("heading", { name: "Quarterly statements" })).toBeInTheDocument();
    expect(screen.getByText("Intended use").parentElement).toHaveTextContent("Intended useEveryday iteration");
    expect(screen.queryByText("Development split")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Upload documents to Quarterly statements" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "quarterly-statement.pdf" })).toHaveAttribute(
      "href",
      "/documents/document-1?from=datasets",
    );
    expect(screen.getByText("Remove the PDF password")).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Status" }), "failed");
    await user.selectOptions(screen.getByRole("combobox", { name: "Format" }), "pdf");
    await waitFor(() => {
      const documentCalls = controls.list.mock.calls.filter(([url]) => url === "/documents/");
      expect(documentCalls.at(-1)?.[1]).toMatchObject({ status: "failed", file_format: "pdf" });
    });
    const summary = screen.getByText("Create a separate dataset").closest("summary");
    expect(summary).not.toBeNull();
    const details = summary!.closest("details")!;
    details.open = true;
    await user.type(within(details).getByLabelText(/^Dataset name/), "Production statements");
    await user.selectOptions(within(details).getByLabelText("Data split"), "test");
    await user.click(within(details).getByRole("checkbox", { name: /^This dataset contains production data/ }));
    await user.click(within(details).getByRole("button", { name: "Create and select dataset" }));

    await waitFor(() =>
      expect(controls.post).toHaveBeenCalledWith("/datasets/", {
        project: "project-1",
        name: "Production statements",
        split: "test",
        is_production: true,
      }),
    );
    expect(controls.workingContext.selectDatasetForProject).toHaveBeenCalledWith("project-1", "dataset-2");
    expect(cachedDatasetIdsWhenSelected).toContain("dataset-2");
    expect(
      queryClient.getQueryData<Page<Dataset>>(["datasets", "project-1"])?.results.map(({ id }) => id),
    ).toContain("dataset-2");
    expect(controls.successToast).toHaveBeenCalledWith('Dataset "Production statements" created and selected');
  });

  it("starts a run with the selected workflow and opens its detail route", async () => {
    const workflow = testWorkflow({ status: "approved" });
    const dataset = testDataset();
    controls.list.mockImplementation((url: string) => {
      if (url === "/workflows/") return Promise.resolve(page([workflow]));
      if (url === "/datasets/") return Promise.resolve(page([dataset]));
      return Promise.resolve(page([]));
    });
    controls.post.mockResolvedValue(testRun({ status: "queued", processed_items: 0 }));
    const { user } = renderWithApp(
      <Routes>
        <Route path="/runs" element={<Runs />} />
        <Route path="/runs/:id" element={<h1>Run detail route</h1>} />
      </Routes>,
      { route: "/runs" },
    );

    await screen.findByRole("option", { name: /Extract statements v1/ });
    await user.selectOptions(screen.getByLabelText(/^Workflow/), "workflow-1");
    expect(screen.getByLabelText(/^Dataset/)).toHaveValue("dataset-1");
    await user.type(screen.getByLabelText("Name"), "September extraction");
    await user.type(screen.getByLabelText("Sample (docs)"), "3");
    await user.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() =>
      expect(controls.post).toHaveBeenCalledWith("/runs/", {
        project: "project-1",
        workflow: "workflow-1",
        dataset: "dataset-1",
        name: "September extraction",
        sample_size: 3,
        execute: true,
      }),
    );
    expect(await screen.findByRole("heading", { name: "Run detail route" })).toBeInTheDocument();
  });

  it("requires explicit confirmation before approving a workflow version", async () => {
    const workflow = testWorkflow();
    controls.list.mockResolvedValue(page([workflow]));
    controls.post.mockResolvedValue({ ...workflow, status: "approved" });
    const { user } = renderWithApp(<Configurations />);

    await user.click(await screen.findByRole("button", { name: "Approve" }));
    const dialog = await screen.findByRole("dialog", { name: "Approve workflow version" });
    expect(within(dialog).getByText(/recorded in the audit trail/)).toBeInTheDocument();
    const approve = within(dialog).getByRole("button", { name: "Approve" });
    expect(approve).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/^Reason/), "Validated against the approved schema");
    await user.click(approve);

    await waitFor(() =>
      expect(controls.post).toHaveBeenCalledWith("/workflows/workflow-1/approve/", {
        reason: "Validated against the approved schema",
      }),
    );
    expect(controls.successToast).toHaveBeenCalledWith("Workflow version approved");
  });

  it("requires an audit reason before retiring a workflow version", async () => {
    const workflow = testWorkflow({ status: "approved" });
    controls.list.mockResolvedValue(page([workflow]));
    controls.post.mockResolvedValue({ ...workflow, status: "retired" });
    const { user } = renderWithApp(<Configurations />);

    await user.click(await screen.findByRole("button", { name: "Retire" }));
    const dialog = await screen.findByRole("dialog", { name: "Retire workflow version" });
    const retire = within(dialog).getByRole("button", { name: "Retire" });
    expect(retire).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/^Reason/), "Superseded by the validated version");
    await user.click(retire);

    await waitFor(() =>
      expect(controls.post).toHaveBeenCalledWith("/workflows/workflow-1/retire/", {
        reason: "Superseded by the validated version",
      }),
    );
  });

  it("creates an evaluation with a numeric relative tolerance", async () => {
    const completedRun = testRun({ status: "succeeded", finished_at: "2026-09-11T12:05:00Z" });
    const existingEvaluation = testEvaluation({
      has_ground_truth: false,
      metrics: {
        documents: 1,
        processed: 1,
        failed: 0,
        has_ground_truth: false,
        classification: {
          labels: ["statement"],
          matrix: [[1]],
          accuracy: 1,
          macro: { f1: 1 },
          micro: { f1: 1 },
          weighted: { f1: 1 },
          other_or_unclassified_rate: 0,
          per_class: {},
        },
        segmentation: { aggregate: { boundary_f1: 0.8 }, per_document: [] },
      },
    });
    controls.list.mockImplementation((url: string) => {
      if (url === "/runs/") return Promise.resolve(page([completedRun]));
      if (url === "/evaluations/") return Promise.resolve(page([existingEvaluation]));
      return Promise.resolve(page([]));
    });
    controls.post.mockResolvedValue(testEvaluation());
    const { user } = renderWithApp(<EvaluationPage />);

    await screen.findByRole("option", { name: /September run/ });
    expect(screen.getByRole("link", { name: "September run" })).toHaveAttribute("href", "/runs/run-1");
    expect(screen.getByText("indicators only")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/^Run/), "run-1");
    const tolerance = screen.getByLabelText("Numeric tolerance");
    await user.clear(tolerance);
    await user.type(tolerance, "0.025");
    await user.click(screen.getByRole("button", { name: "Evaluate" }));

    await waitFor(() =>
      expect(controls.post).toHaveBeenCalledWith("/evaluations/", {
        run: "run-1",
        numeric_tolerance: 0.025,
      }),
    );
    expect(controls.successToast).toHaveBeenCalledWith("Evaluation created");
  });

  it("validates evaluation tolerance before sending a request", async () => {
    controls.list.mockImplementation((url: string) =>
      Promise.resolve(url === "/runs/" ? page([testRun({ status: "succeeded" })]) : page([])),
    );
    const { user } = renderWithApp(<EvaluationPage />);

    await screen.findByRole("option", { name: /September run/ });
    await user.selectOptions(screen.getByLabelText(/^Run/), "run-1");
    const tolerance = screen.getByLabelText("Numeric tolerance");
    await user.clear(tolerance);
    await user.type(tolerance, "-0.1");
    await user.click(screen.getByRole("button", { name: "Evaluate" }));

    expect(await screen.findByText("Enter zero or a positive decimal.")).toBeInTheDocument();
    expect(controls.post).not.toHaveBeenCalled();
  });
});
