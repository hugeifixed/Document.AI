import { Route, Routes } from "react-router-dom";
import type { Me } from "@/api/types";
import { AppShell } from "@/layouts/AppShell";
import { Dashboard } from "@/pages/Dashboard";
import { Exports } from "@/pages/Exports";
import { Labeling } from "@/pages/Labeling";
import { Results } from "@/pages/Results";
import { Settings } from "@/pages/Settings";
import { usePrefs } from "@/store/prefs";
import { useWorkingContext } from "@/workspace/context";
import {
  page,
  testDashboard,
  testDataset,
  testDocument,
  testField,
  testLabel,
  testProject,
  testRun,
  testUser,
} from "@/test/fixtures";
import { renderWithApp, screen, waitFor, within } from "@/test/test-utils";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  list: vi.fn(),
  signOut: vi.fn(),
  session: { user: null as Me | null },
}));

vi.mock("@/auth/Session", () => ({
  useSession: () => ({ user: mocks.session.user, signOut: mocks.signOut }),
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  get: mocks.get,
  list: mocks.list,
}));

describe("workspace pages and shell", () => {
  const user = testUser({ username: "alex" });
  const project = testProject();
  const dataset = testDataset();
  const run = testRun();
  const dashboard = testDashboard();

  beforeEach(() => {
    mocks.session.user = user;
    mocks.signOut.mockReset().mockResolvedValue(undefined);
    localStorage.setItem("docai-product-tour:1:alex", "acknowledged");
    usePrefs.setState({
      theme: "system",
      pageSize: 25,
      sidebarHidden: false,
    });
    useWorkingContext.setState({ projectId: project.id, datasetId: dataset.id });
    mocks.get.mockReset().mockImplementation((url: string) => {
      if (url === "/dashboard/") return Promise.resolve(dashboard);
      if (url === "/projects/") return Promise.resolve(page([project]));
      if (url === "/datasets/") return Promise.resolve(page([dataset]));
      if (url === "/me/") return Promise.resolve(user);
      if (url === `/runs/${run.id}/`) return Promise.resolve(run);
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });
    mocks.list.mockReset().mockImplementation((url: string) => {
      if (url === "/runs/") return Promise.resolve(page([run]));
      if (url === "/documents/") return Promise.resolve(page([testDocument()]));
      if (url === "/labels/") return Promise.resolve(page([testLabel({ document: "document-1", status: "final" })]));
      if (url === "/fields/") return Promise.resolve(page([testField()]));
      return Promise.reject(new Error(`Unexpected LIST ${url}`));
    });
  });

  it("keeps role-aware navigation, working context, drawer, and sidebar preferences usable", async () => {
    const { user: operator } = renderWithApp(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/results" element={<h1>Result details</h1>} />
        </Route>
      </Routes>,
      { route: "/results" },
    );

    expect(await screen.findByRole("heading", { name: "Result details" })).toBeInTheDocument();
    const sidebar = document.querySelector("#primary-sidebar");
    expect(sidebar).not.toBeNull();
    expect(await within(sidebar as HTMLElement).findByLabelText("1 items")).toBeInTheDocument();
    expect(await within(sidebar as HTMLElement).findByLabelText("3 items")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: `Project: ${project.name}` })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: `Dataset: ${dataset.name}` })).toBeInTheDocument();

    await operator.click(within(sidebar as HTMLElement).getByRole("button", { name: "Hide navigation" }));
    expect(usePrefs.getState().sidebarHidden).toBe(true);
    await operator.click(screen.getByRole("button", { name: "Show navigation" }));
    expect(usePrefs.getState().sidebarHidden).toBe(false);

    await operator.click(screen.getByRole("button", { name: "Open navigation" }));
    const drawer = screen.getByRole("dialog", { name: "Navigation" });
    expect(drawer).toHaveAttribute("open");
    await operator.click(within(drawer).getAllByRole("button", { name: "Close navigation" })[0]);
    expect(drawer).not.toHaveAttribute("open");

    await operator.selectOptions(within(sidebar as HTMLElement).getByLabelText("Active project"), "");
    expect(useWorkingContext.getState()).toMatchObject({ projectId: null, datasetId: null });
  });

  it("shows a recoverable shell error when logout fails", async () => {
    mocks.signOut.mockRejectedValueOnce(new Error("offline"));
    const { user: operator } = renderWithApp(
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<h1>Home</h1>} />
        </Route>
      </Routes>,
    );

    await screen.findByRole("heading", { name: "Home" });
    await operator.click(screen.getByRole("button", { name: "Log out" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn’t log you out");
  });

  it("clears a persisted dataset that is no longer in the selected project", async () => {
    useWorkingContext.setState({ projectId: project.id, datasetId: "removed-dataset" });
    renderWithApp(
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<h1>Home</h1>} />
        </Route>
      </Routes>,
    );

    await screen.findByRole("heading", { name: "Home" });
    await waitFor(() => expect(useWorkingContext.getState()).toMatchObject({ projectId: project.id, datasetId: null }));
  });

  it("clears a persisted project and dataset when the project is no longer available", async () => {
    useWorkingContext.setState({ projectId: "removed-project", datasetId: "removed-dataset" });
    renderWithApp(
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<h1>Home</h1>} />
        </Route>
      </Routes>,
    );

    await screen.findByRole("heading", { name: "Home" });
    await waitFor(() => expect(useWorkingContext.getState()).toMatchObject({ projectId: null, datasetId: null }));
  });

  it("presents operational dashboard status and role-specific actions", async () => {
    renderWithApp(<Dashboard />);

    expect(await screen.findByRole("heading", { name: "Welcome back, alex" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /Continue review/ })).toHaveAttribute("href", "/review");
    expect(screen.getByRole("link", { name: "Open queue" })).toHaveAttribute("href", "/review");
    expect(screen.queryByRole("navigation", { name: "Quick actions" })).not.toBeInTheDocument();
    expect(await screen.findByText("September run")).toBeInTheDocument();
    expect(screen.getByText("Layout analysis failed")).toBeInTheDocument();
    expect(screen.getByText("Runs to date").parentElement).toHaveTextContent("5");
    expect(screen.getByText("Datasets").parentElement).toHaveTextContent("1");
  });

  it("provides exact download URLs for each export format", async () => {
    mocks.list.mockImplementation((url: string) => {
      if (url === "/runs/")
        return Promise.resolve(
          page([
            {
              ...run,
              status: "succeeded",
              processed_items: run.total_items,
              guidance: { ...run.guidance!, export_ready: true },
            },
          ]),
        );
      return Promise.resolve(page([]));
    });
    renderWithApp(<Exports />);

    const row = await screen.findByRole("row", { name: /September run/ });
    expect(within(row).getByRole("link", { name: "JSON package" })).toHaveAttribute(
      "href",
      `/api/v1/runs/${run.id}/export/json/`,
    );
    expect(within(row).getByRole("link", { name: "CSV fields" })).toHaveAttribute(
      "href",
      `/api/v1/runs/${run.id}/export/csv/`,
    );
    expect(within(row).getByRole("link", { name: "Excel workbook" })).toHaveAttribute(
      "href",
      `/api/v1/runs/${run.id}/export/xlsx/`,
    );
  });

  it("explains ground-truth permissions and shows label counts for reviewers", async () => {
    mocks.session.user = testUser({ roles: ["docai_viewers"] });
    const restricted = renderWithApp(<Labeling />);
    expect(screen.getByText("Creating ground truth requires the reviewer role.")).toBeInTheDocument();
    restricted.unmount();

    mocks.session.user = user;
    renderWithApp(<Labeling />);
    await waitFor(() =>
      expect(screen.getByText(/Labels in this dataset:/)).toHaveTextContent("Labels in this dataset: 1 final."),
    );
    expect(screen.getByRole("link", { name: "statement.txt" })).toHaveAttribute("href", "/labeling/document-1");
  });

  it("applies result filters through the API contract", async () => {
    const { user: operator } = renderWithApp(<Results />);
    await screen.findByRole("option", { name: "September run (running)" });

    await operator.selectOptions(screen.getByLabelText("Run"), run.id);
    await operator.selectOptions(screen.getByLabelText("Grounded"), "false");

    await waitFor(() => {
      const fieldCalls = mocks.list.mock.calls.filter(([url]) => url === "/fields/");
      expect(fieldCalls.at(-1)?.[1]).toMatchObject({
        run: run.id,
        grounded: "false",
        project: project.id,
        dataset: dataset.id,
      });
    });
    expect(screen.getByRole("link", { name: "statement.txt" })).toHaveAttribute(
      "href",
      "/documents/document-1?run=run-1&from=results",
    );
  });

  it("persists appearance and table-size preferences", async () => {
    const { user: operator } = renderWithApp(<Settings />);

    expect(await screen.findByText("alex")).toBeInTheDocument();
    await operator.click(screen.getByRole("radio", { name: "Dark" }));
    await operator.selectOptions(screen.getByLabelText("Default rows per page"), "50");

    expect(usePrefs.getState()).toMatchObject({ theme: "dark", pageSize: 50 });
    expect(screen.getByText("docai_operators, docai_reviewers, docai_approvers")).toBeInTheDocument();
  });
});
