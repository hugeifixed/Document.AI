import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Outlet, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError, get } from "@/common/api/client";
import type { Document, Run } from "@/common/types/api";
import { acknowledgeProductTour } from "@/components/productTourStorage";
import { AppShell } from "@/layouts/AppShell";
import { authorizedQueryData, useWorkingContext } from "@/workspace/context";
import {
  useDocumentWorkspaceScope,
  useRunWorkspaceScope,
  useWorkspaceDraft,
  useWorkspaceNavigation,
  workspaceChangeHint,
  workspaceDestination,
  WorkspaceNavigationProvider,
} from "@/workspace/navigation";
import { page, testDataset, testDocument, testProject, testRun, testUser } from "./fixtures";
import { act, createTestQueryClient, fireEvent, renderWithApp, screen, waitFor, within } from "./test-utils";

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/common/api/client", async (original) => ({ ...(await original<typeof import("@/common/api/client")>()), get: api.get }));
vi.mock("@/auth/Session", () => ({ useSession: () => ({ user: testUser(), signOut: vi.fn() }) }));
vi.mock("@/journey/guidance", () => ({ useJourneyDashboard: () => ({ data: undefined }) }));

const projects = [testProject(), testProject({ id: "project-2", name: "Second project" })];
const datasets = [
  testDataset(),
  testDataset({ id: "dataset-2", name: "Second dataset" }),
  testDataset({ id: "dataset-3", project: "project-2", name: "Other project dataset" }),
];

function Location() {
  const location = useLocation();
  const scope = useWorkingContext();
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="location">{location.pathname + location.search}</output>
      <output data-testid="scope">
        {scope.projectId}:{scope.datasetId}
      </output>
      <Link to="/documents/document-2">Second document</Link>
      <button onClick={() => void navigate(-1)}>Go back</button>
    </>
  );
}
function Draft() {
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  useWorkspaceDraft(!!value, saving);
  return (
    <>
      <label>
        Draft value
        <input value={value} onChange={(event) => setValue(event.target.value)} />
      </label>
      <button onClick={() => setSaving(true)}>Save draft</button>
    </>
  );
}
function DocumentDetail() {
  const { documentId } = useParams();
  const document = useQuery({
    queryKey: ["test-document", documentId],
    queryFn: () => get<Document>(`/documents/${documentId}/`),
  });
  useDocumentWorkspaceScope(authorizedQueryData(document));
  return <Draft />;
}
function RunDetail() {
  const { id } = useParams();
  const run = useQuery({
    queryKey: ["test-run", id],
    queryFn: () => get<Run>(`/runs/${id}/`),
  });
  useRunWorkspaceScope(authorizedQueryData(run));
  return <Draft />;
}
function Pickers() {
  const { projectId, datasetId } = useWorkingContext();
  const { changeProject, changeDataset, saving } = useWorkspaceNavigation();
  return (
    <>
      <select
        aria-label="Active project"
        value={projectId ?? ""}
        disabled={saving}
        onChange={(event) => changeProject(event.target.value || null)}
      >
        <option value="">All projects</option>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      <select
        aria-label="Active dataset"
        value={datasetId ?? ""}
        disabled={saving}
        onChange={(event) => changeDataset(event.target.value || null)}
      >
        <option value="">All datasets</option>
        {datasets.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name}
          </option>
        ))}
      </select>
    </>
  );
}
function TestShell() {
  return (
    <WorkspaceNavigationProvider>
      <Pickers />
      <Outlet />
    </WorkspaceNavigationProvider>
  );
}
function mount(route: string, realShell = false, client = createTestQueryClient()) {
  return renderWithApp(
    <>
      <Location />
      <Routes>
        <Route element={realShell ? <AppShell /> : <TestShell />}>
          <Route path="/documents/:documentId" element={<DocumentDetail />} />
          <Route path="/review/:documentId" element={<Draft />} />
          <Route path="/labeling/:documentId" element={<Draft />} />
          <Route path="/workflows/new" element={<Draft />} />
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="*" element={<p>List contents</p>} />
        </Route>
      </Routes>
    </>,
    { route, queryClient: client },
  );
}

beforeEach(() => {
  useWorkingContext.getState().selectDatasetForProject("project-1", "dataset-1");
  acknowledgeProductTour("reviewer");
  api.get.mockReset().mockImplementation(async (url: string, params?: Record<string, unknown>) => {
    if (url === "/projects/") return page(projects);
    if (url === "/datasets/") return page(datasets.filter((item) => item.project === params?.project));
    const project = projects.find((item) => url === `/projects/${item.id}/`);
    if (project) return project;
    const dataset = datasets.find((item) => url === `/datasets/${item.id}/`);
    if (dataset) return dataset;
    if (url === "/documents/document-1/") return testDocument();
    if (url === "/documents/document-2/") return testDocument({ id: "document-2", dataset: "dataset-3" });
    if (url === "/runs/run-1/") return testRun();
    if (url === "/runs/run-2/") return testRun({ id: "run-2", project: "project-2", dataset: "dataset-3" });
    throw new Error(`Unmocked GET ${url}`);
  });
});

describe("workspace navigation", () => {
  it.each([
    ["/workflows/new/", "/configurations", "workflow versions"],
    ["/WORKFLOWS/new", "/configurations", "workflow versions"],
    ["/DOCUMENTS/document-1", "/datasets", "documents"],
    ["/review/document-1//", "/datasets", "documents"],
    ["/LABELING/document-1/", "/datasets", "documents"],
    ["/runs/run-1//", "/runs", "runs"],
  ])("guards the router-accepted variant %s", async (route, destination, hint) => {
    const { user } = mount(route);
    expect(workspaceChangeHint(route)).toBe(`Changing workspace opens its ${hint}.`);
    await user.type(screen.getByLabelText("Draft value"), "Unsaved");
    await user.selectOptions(screen.getByRole("combobox", { name: "Active project" }), "project-2");
    act(() => (screen.getByRole("dialog", { name: "Discard unsaved changes?" }) as HTMLDialogElement).close());
    expect(screen.getByTestId("location")).toHaveTextContent(route);
    expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1");
    expect(screen.getByLabelText("Draft value")).toHaveValue("Unsaved");
    await user.selectOptions(screen.getByRole("combobox", { name: "Active project" }), "project-2");
    await user.click(screen.getByRole("button", { name: "Discard and switch" }));
    expect(screen.getByTestId("location").textContent).toBe(destination);
    expect(screen.getByTestId("scope")).toHaveTextContent("project-2:");
    expect(screen.queryByLabelText("Draft value")).not.toBeInTheDocument();
  });

  it.each(["/documents/document-1", "/review/document-1", "/labeling/document-1"])(
    "keeps both selectors and draft on cancellation from %s",
    async (route) => {
      const { user } = mount(route);
      await user.type(screen.getByLabelText("Draft value"), "Unsaved label");
      await user.selectOptions(screen.getByRole("combobox", { name: "Active project" }), "project-2");
      const dialog = screen.getByRole("dialog", { name: "Discard unsaved changes?" });
      expect(screen.getByRole("combobox", { name: "Active project" })).toHaveValue("project-1");
      expect(screen.getByRole("combobox", { name: "Active dataset" })).toHaveValue("dataset-1");
      act(() => (dialog as HTMLDialogElement).close());
      expect(screen.getByTestId("location")).toHaveTextContent(route);
      expect(screen.getByLabelText("Draft value")).toHaveValue("Unsaved label");
      expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1");
    },
  );

  it("discards a draft and changes scope and destination together", async () => {
    const { user } = mount("/labeling/document-1?run=old&field=field-1&page=4");
    await user.type(screen.getByLabelText("Draft value"), "Unsaved");
    await user.selectOptions(screen.getByRole("combobox", { name: "Active dataset" }), "dataset-2");
    await user.click(screen.getByRole("button", { name: "Discard and switch" }));
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/datasets$/);
    expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-2");
    expect(screen.queryByLabelText("Draft value")).not.toBeInTheDocument();
  });

  it("leaves a configuration draft after a confirmed project switch", async () => {
    const { user } = mount("/workflows/new");
    await user.type(screen.getByLabelText("Draft value"), "New config");
    await user.selectOptions(screen.getByRole("combobox", { name: "Active project" }), "project-2");
    await user.click(screen.getByRole("button", { name: "Discard and switch" }));
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/configurations$/);
    expect(screen.getByTestId("scope")).toHaveTextContent("project-2:");
  });

  it("disables both context selectors during saving", async () => {
    const { user } = mount("/labeling/document-1");
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    expect(screen.getByRole("combobox", { name: "Active project" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Active dataset" })).toBeDisabled();
  });

  it.each(["datasets", "runs", "results", "review"])(
    "resets %s pagination and resource filters while preserving independent filters",
    async (route) => {
      const { user } = mount(
        `/${route}?page=9&run=old&dataset=dataset-1&workflow=old&field=old&q=invoice&status=failed`,
      );
      await user.selectOptions(screen.getByRole("combobox", { name: "Active dataset" }), "dataset-2");
      expect(screen.getByTestId("location")).toHaveTextContent(`/${route}?q=invoice&status=failed`);
      expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-2");
    },
  );

  it("does nothing when the same project is selected", () => {
    mount("/results?page=9");
    fireEvent.change(screen.getByRole("combobox", { name: "Active project" }), { target: { value: "project-1" } });
    expect(screen.getByTestId("location")).toHaveTextContent("/results?page=9");
    expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1");
  });

  it("aligns successive cached document routes and Back with the authorized dataset project", async () => {
    const client = createTestQueryClient();
    client.setQueryData(["datasets", "project-1"], page(datasets));
    client.setQueryData(["test-document", "document-1"], testDocument());
    client.setQueryData(["test-document", "document-2"], testDocument({ id: "document-2", dataset: "dataset-3" }));
    const { user } = mount("/documents/document-1", false, client);
    await user.click(screen.getByRole("link", { name: "Second document" }));
    await waitFor(() => expect(screen.getByTestId("scope")).toHaveTextContent("project-2:dataset-3"));
    await user.click(screen.getByRole("button", { name: "Go back" }));
    await waitFor(() => expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1"));
    expect(api.get.mock.calls.some(([url]) => url.startsWith("/datasets/dataset-"))).toBe(false);
  });

  it("realigns a document after Back reverses an explicit workspace switch", async () => {
    const client = createTestQueryClient();
    client.setQueryData(["datasets", "project-1"], page(datasets));
    const { user } = mount("/documents/document-1", false, client);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/documents/document-1/"));
    await user.selectOptions(screen.getByRole("combobox", { name: "Active dataset" }), "dataset-2");
    expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-2");
    await user.click(screen.getByRole("button", { name: "Go back" }));
    await waitFor(() => expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1"));
    expect(screen.getByTestId("location")).toHaveTextContent("/documents/document-1");
  });

  it("does not align from stale cached metadata when current access fails", async () => {
    const client = createTestQueryClient();
    client.setQueryData(["datasets", "old-list"], page([datasets[2]]), { updatedAt: 1 });
    const original = api.get.getMockImplementation()!;
    api.get.mockImplementation((url: string, params?: Record<string, unknown>) => {
      if (url === "/datasets/dataset-3/") return Promise.reject(new ApiError(404, { message: "Not found" }));
      return original(url, params);
    });
    mount("/documents/document-2", false, client);
    await waitFor(() => expect(client.getQueryState(["dataset", "dataset-3"])?.status).toBe("error"));
    expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1");
  });

  it.each([
    ["document", 403, 0],
    ["document", 404, 10_000],
    ["run", 403, 0],
    ["run", 404, 10_000],
  ] as const)(
    "retains selected scope while a stale %s refetch fails with %i (staleTime %i)",
    async (kind, status, staleTime) => {
      const client = createTestQueryClient();
      client.setDefaultOptions({ queries: { retry: false, staleTime } });
      const resourceId = `${kind}-2`;
      const queryKey = [`test-${kind}`, resourceId];
      client.setQueryData(
        queryKey,
        kind === "document"
          ? testDocument({ id: resourceId, dataset: "dataset-3" })
          : testRun({ id: resourceId, project: "project-2", dataset: "dataset-3" }),
        { updatedAt: 1 },
      );
      client.setQueryData(["datasets", "project-2"], page([datasets[2]]));
      let reject!: (error: Error) => void;
      const original = api.get.getMockImplementation()!;
      api.get.mockImplementation((url: string, params?: Record<string, unknown>) => {
        if (url === `/${kind}s/${resourceId}/`)
          return new Promise((_resolve, fail) => {
            reject = fail;
          });
        return original(url, params);
      });
      mount(`/${kind}s/${resourceId}`, true, client);
      await waitFor(() => expect(reject).toBeDefined());
      expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1");
      await act(async () => reject(new ApiError(status, { message: "Unavailable" })));
      await waitFor(() => expect(client.getQueryState(queryKey)?.status).toBe("error"));
      expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1");
    },
  );

  it.each(["document", "run"] as const)(
    "aligns a stale %s only after its new GET succeeds with staleTime zero",
    async (kind) => {
      const client = createTestQueryClient();
      const resourceId = `${kind}-2`;
      const record =
        kind === "document"
          ? testDocument({ id: resourceId, dataset: "dataset-3" })
          : testRun({ id: resourceId, project: "project-2", dataset: "dataset-3" });
      client.setQueryData([`test-${kind}`, resourceId], record, { updatedAt: 1 });
      client.setQueryData(["datasets", "project-2"], page([datasets[2]]));
      let resolve!: (record: Document | Run) => void;
      const original = api.get.getMockImplementation()!;
      api.get.mockImplementation((url: string, params?: Record<string, unknown>) => {
        if (url === `/${kind}s/${resourceId}/`)
          return new Promise((accept) => {
            resolve = accept;
          });
        return original(url, params);
      });
      mount(`/${kind}s/${resourceId}`, false, client);
      await waitFor(() => expect(resolve).toBeDefined());
      expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1");
      await act(async () => resolve(record));
      await waitFor(() => expect(screen.getByTestId("scope")).toHaveTextContent("project-2:dataset-3"));
    },
  );

  it.each(["project", "dataset"] as const)(
    "retains a selected %s absent from the first page when its detail is available",
    async (kind) => {
      const original = api.get.getMockImplementation()!;
      api.get.mockImplementation((url: string, params?: Record<string, unknown>) => {
        if (url === `/${kind}s/`) return Promise.resolve(page([], { count: 201, total_pages: 2 }));
        return original(url, params);
      });
      mount("/results", true);
      await waitFor(() => expect(api.get).toHaveBeenCalledWith(`/${kind}s/${kind}-1/`, undefined, expect.any(Object)));
      expect(
        await screen.findByRole("link", {
          name: kind === "project" ? `Project: ${projects[0].name}` : `Dataset: ${datasets[0].name}`,
        }),
      ).toBeInTheDocument();
      expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1");
    },
  );

  it.each([
    ["project", 403],
    ["project", 500],
    ["dataset", 403],
    ["dataset", 500],
  ] as const)("retains a selected %s after a %i detail failure", async (kind, status) => {
    const original = api.get.getMockImplementation()!;
    api.get.mockImplementation((url: string, params?: Record<string, unknown>) => {
      if (url === `/${kind}s/`) return Promise.resolve(page([]));
      if (url === `/${kind}s/${kind}-1/`) return Promise.reject(new ApiError(status, { message: "Unavailable" }));
      return original(url, params);
    });
    const { queryClient } = mount("/results", true);
    await waitFor(() => expect(queryClient.getQueryState([kind, `${kind}-1`])?.status).toBe("error"));
    expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1");
  });

  it("repairs a dataset whose authoritative detail belongs to another project", async () => {
    const original = api.get.getMockImplementation()!;
    api.get.mockImplementation((url: string, params?: Record<string, unknown>) => {
      if (url === "/datasets/") return Promise.resolve(page([]));
      if (url === "/datasets/dataset-1/") return Promise.resolve(testDataset({ project: "project-2" }));
      return original(url, params);
    });
    mount("/results?page=3", true);
    await waitFor(() =>
      expect(useWorkingContext.getState()).toMatchObject({ projectId: "project-1", datasetId: null }),
    );
  });

  it("defers a late selected-dataset 404 through discard cancellation until the draft is clean", async () => {
    let reject!: (error: Error) => void;
    const original = api.get.getMockImplementation()!;
    api.get.mockImplementation((url: string, params?: Record<string, unknown>) => {
      if (url === "/datasets/") return Promise.resolve(page(datasets.filter((item) => item.id !== "dataset-1")));
      if (url === "/datasets/dataset-1/")
        return new Promise((_resolve, fail) => {
          reject = fail;
        });
      return original(url, params);
    });
    const { user, queryClient } = mount("/labeling/document-1?page=3", true);
    await waitFor(() => expect(reject).toBeDefined());
    await user.type(screen.getByLabelText("Draft value"), "Unsaved");
    await user.selectOptions(screen.getByRole("combobox", { name: "Active dataset" }), "dataset-2");
    await act(async () => reject(new ApiError(404, { message: "Not found" })));
    await waitFor(() => expect(queryClient.getQueryState(["dataset", "dataset-1"])?.status).toBe("error"));
    expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1");
    act(() => (screen.getByRole("dialog", { name: "Discard unsaved changes?" }) as HTMLDialogElement).close());
    expect(screen.getByTestId("location")).toHaveTextContent("/labeling/document-1?page=3");
    expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1");
    expect(screen.getByRole("combobox", { name: "Active dataset" })).toHaveValue("dataset-1");
    expect(screen.getByLabelText("Draft value")).toHaveValue("Unsaved");
    await user.clear(screen.getByLabelText("Draft value"));
    await waitFor(() => expect(useWorkingContext.getState().datasetId).toBeNull());
  });

  it("defers a late selected-project 404 while saving even a clean draft", async () => {
    let reject!: (error: Error) => void;
    const original = api.get.getMockImplementation()!;
    api.get.mockImplementation((url: string, params?: Record<string, unknown>) => {
      if (url === "/projects/") return Promise.resolve(page([projects[1]]));
      if (url === "/projects/project-1/")
        return new Promise((_resolve, fail) => {
          reject = fail;
        });
      return original(url, params);
    });
    const { user, queryClient } = mount("/workflows/new", true);
    await waitFor(() => expect(reject).toBeDefined());
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    await act(async () => reject(new ApiError(404, { message: "Not found" })));
    await waitFor(() => expect(queryClient.getQueryState(["project", "project-1"])?.status).toBe("error"));
    expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1");
    expect(screen.getByRole("combobox", { name: "Active project" })).toBeDisabled();
    expect(screen.getByTestId("location")).toHaveTextContent("/workflows/new");
  });

  it("ignores a missing selected dataset response after another dataset is selected", async () => {
    let reject!: (error: Error) => void;
    const original = api.get.getMockImplementation()!;
    api.get.mockImplementation((url: string, params?: Record<string, unknown>) => {
      if (url === "/datasets/") return Promise.resolve(page(datasets.filter((item) => item.id !== "dataset-1")));
      if (url === "/datasets/dataset-1/")
        return new Promise((_resolve, fail) => {
          reject = fail;
        });
      return original(url, params);
    });
    const { user } = mount("/results", true);
    await waitFor(() => expect(reject).toBeDefined());
    await user.selectOptions(screen.getByRole("combobox", { name: "Active dataset" }), "dataset-2");
    await act(async () => reject(new ApiError(404, { message: "Not found" })));
    expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-2");
  });

  it("uses dataset detail when authorized metadata is absent from the first page", async () => {
    const original = api.get.getMockImplementation()!;
    api.get.mockImplementation((url: string, params?: Record<string, unknown>) => {
      if (url === "/projects/" || url === "/datasets/")
        return Promise.resolve(page([], { count: 201, total_pages: 2 }));
      return original(url, params);
    });
    mount("/documents/document-2", true);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Active project" })).toHaveValue("project-2"));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Active dataset" })).toHaveValue("dataset-3"));
    expect(await screen.findByRole("link", { name: "Project: Second project" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Dataset: Other project dataset" })).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith("/datasets/dataset-3/", undefined, expect.any(Object));
  });

  it("keeps selected scope when dataset access fails", async () => {
    const original = api.get.getMockImplementation()!;
    api.get.mockImplementation((url: string, params?: Record<string, unknown>) => {
      if (url === "/datasets/dataset-3/") return Promise.reject(new ApiError(403, { message: "Forbidden" }));
      return original(url, params);
    });
    const { queryClient } = mount("/documents/document-2");
    await waitFor(() => expect(queryClient.getQueryState(["dataset", "dataset-3"])?.status).toBe("error"));
    expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-1");
  });

  it("ignores a late dataset response after a user scope switch", async () => {
    let finish!: (value: (typeof datasets)[number]) => void;
    const original = api.get.getMockImplementation()!;
    api.get.mockImplementation((url: string, params?: Record<string, unknown>) => {
      if (url === "/datasets/dataset-3/")
        return new Promise((resolve) => {
          finish = resolve;
        });
      return original(url, params);
    });
    const { user } = mount("/documents/document-2");
    await waitFor(() => expect(finish).toBeDefined());
    await user.selectOptions(screen.getByRole("combobox", { name: "Active dataset" }), "dataset-2");
    await act(async () => finish(datasets[2]));
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/datasets$/);
    expect(screen.getByTestId("scope")).toHaveTextContent("project-1:dataset-2");
  });

  it("does not retain a draft confirmation across a different resource route", async () => {
    const { user } = mount("/documents/document-1");
    await user.type(screen.getByLabelText("Draft value"), "Unsaved");
    await user.selectOptions(screen.getByRole("combobox", { name: "Active project" }), "project-2");
    // Simulate another navigation event while the native modal is open.
    fireEvent.click(screen.getByRole("link", { name: "Second document" }));
    await waitFor(() => expect(screen.getByTestId("scope")).toHaveTextContent("project-2:dataset-3"));
    expect(screen.queryByRole("dialog", { name: "Discard unsaved changes?" })).not.toBeInTheDocument();
  });

  it("aligns run details using the run's authoritative project and dataset", async () => {
    function RunDetail() {
      useRunWorkspaceScope(testRun({ project: "project-2", dataset: "dataset-3" }));
      return null;
    }
    renderWithApp(
      <WorkspaceNavigationProvider>
        <Location />
        <Pickers />
        <RunDetail />
      </WorkspaceNavigationProvider>,
      { route: "/runs/run-1" },
    );
    await waitFor(() => expect(screen.getByTestId("scope")).toHaveTextContent("project-2:dataset-3"));
    expect(workspaceDestination("/runs/run-1", "?dataset=old&page=4")).toBe("/runs");
  });

  it("associates the document navigation hint with desktop and mobile selectors", async () => {
    const { user } = mount("/documents/document-1", true);
    const project = screen.getByRole("combobox", { name: "Active project" });
    expect(project).toHaveAccessibleDescription("Changing workspace opens its documents.");
    expect(screen.getByRole("combobox", { name: "Active dataset" })).toHaveAccessibleDescription(
      "Changing workspace opens its documents.",
    );
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    const drawer = screen.getByRole("dialog", { name: "Navigation" });
    expect(within(drawer).getByLabelText("Active project")).toHaveAccessibleDescription(
      "Changing workspace opens its documents.",
    );
    expect(within(drawer).getByLabelText("Active dataset")).toHaveAccessibleDescription(
      "Changing workspace opens its documents.",
    );
  });
});
