import { act, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import type { Document, Page } from "@/common/types/api";
import { DocumentPage, LabelPage, ReviewPage } from "@/pages/ReviewWorkspace";
import { page, testDocument, testField, testLabel, testRun, testRunItem } from "@/test/fixtures";
import { createTestQueryClient, renderWithApp, screen } from "@/test/test-utils";

const { getDocument, listResources, postResource, session, successToast } = vi.hoisted(() => ({
  getDocument: vi.fn(),
  listResources: vi.fn(),
  postResource: vi.fn(),
  session: { roles: ["docai_reviewers"] as string[] },
  successToast: vi.fn(),
}));

vi.mock("@/auth/Session", () => ({
  useSession: () => ({ user: { roles: session.roles } }),
}));
vi.mock("@/common/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/common/api/client")>()),
  get: getDocument,
  list: listResources,
  post: postResource,
}));
vi.mock("sonner", () => ({ toast: { success: successToast, error: vi.fn() } }));

const emptyPage: Page<never> = {
  count: 0,
  page: 1,
  page_size: 200,
  total_pages: 1,
  results: [],
};

describe("ReviewWorkspace data loading", () => {
  beforeEach(() => {
    getDocument.mockReset();
    listResources.mockReset().mockResolvedValue(emptyPage);
    postResource.mockReset();
    successToast.mockReset();
    session.roles = ["docai_reviewers"];
  });

  it("loads document status in parallel and caches runs by dataset", async () => {
    let resolveDocument!: (document: Document) => void;
    getDocument.mockReturnValue(
      new Promise<Document>((resolve) => {
        resolveDocument = resolve;
      }),
    );
    const queryClient = createTestQueryClient();

    renderWithApp(
      <Routes>
        <Route path="/review/:documentId" element={<ReviewPage />} />
      </Routes>,
      { route: "/review/document-1", queryClient },
    );

    await waitFor(() =>
      expect(listResources).toHaveBeenCalledWith(
        "/run-items/",
        expect.objectContaining({ document: "document-1" }),
        expect.any(Object),
      ),
    );
    expect(listResources.mock.calls.some(([url]) => url === "/runs/")).toBe(false);

    await act(async () =>
      resolveDocument({
        id: "document-1",
        dataset: "dataset-1",
        dataset_name: "Quarterly statements",
        original_filename: "statement.txt",
        file_format: "txt",
        sha256: "abc123",
        size_bytes: 12,
        page_count: 0,
        sheet_count: 0,
        status: "processed",
        validation_errors: [],
        created: "2026-09-11T00:00:00Z",
        modified: "2026-09-11T00:00:00Z",
        units: [],
      }),
    );

    await waitFor(() =>
      expect(listResources).toHaveBeenCalledWith(
        "/runs/",
        expect.objectContaining({ dataset: "dataset-1", document: "document-1" }),
        expect.any(Object),
      ),
    );
    expect(queryClient.getQueryState(["runs", "document", "document-1"])).toBeDefined();
  });

  it.each([
    ["September statements", "September statements"],
    ["Extract statements v3 · Banking · Sep 13, 2026, 17:18", "Extract statements v3 · Banking · Sep 13, 2026, 17:18"],
    ["", "Extract statements v3"],
  ])("shows one linked run identity for a single result: %s", async (name, expectedLabel) => {
    const run = testRun({ name, status: "succeeded", workflow_version: 3 });
    getDocument.mockImplementation((url: string) =>
      Promise.resolve(url.includes("/units/") ? { kind: "page", index: 0, content: "Daniel Silva" } : testDocument()),
    );
    listResources.mockImplementation((url: string) => {
      if (url === "/run-items/") return Promise.resolve(page([testRunItem()]));
      if (url === "/runs/") return Promise.resolve(page([run]));
      return Promise.resolve(page([]));
    });

    renderWithApp(
      <Routes>
        <Route path="/documents/:documentId" element={<DocumentPage />} />
      </Routes>,
      { route: "/documents/document-1?run=run-1" },
    );

    const provenance = await screen.findByLabelText("Processing provenance");
    expect(provenance).toHaveTextContent("Processed in");
    const link = within(provenance).getByRole("link", { name: expectedLabel });
    expect(link).toHaveAttribute("href", "/runs/run-1");
    expect(link).toHaveAttribute("title", expectedLabel);
    expect(provenance.textContent).toBe(`Processed in${expectedLabel}Succeeded`);
    expect(provenance).toHaveTextContent("Succeeded");
    expect(screen.queryByRole("combobox", { name: "Result version" })).not.toBeInTheDocument();
  });

  it("switches between only this document's result versions", async () => {
    const latest = testRun({ id: "run-2", name: "October statements", status: "succeeded", workflow_version: 2 });
    const earlier = testRun({ name: "September statements", status: "succeeded", workflow_version: 1 });
    getDocument.mockImplementation((url: string) =>
      Promise.resolve(url.includes("/units/") ? { kind: "page", index: 0, content: "Daniel Silva" } : testDocument()),
    );
    listResources.mockImplementation((url: string) => {
      if (url === "/run-items/")
        return Promise.resolve(page([testRunItem({ run: "run-2" }), testRunItem({ id: "item-2", run: "run-1" })]));
      if (url === "/runs/") return Promise.resolve(page([latest, earlier]));
      return Promise.resolve(page([]));
    });
    const queryClient = createTestQueryClient();
    const { user } = renderWithApp(
      <Routes>
        <Route path="/documents/:documentId" element={<DocumentPage />} />
      </Routes>,
      { route: "/documents/document-1?run=run-2", queryClient },
    );

    const resultVersion = await screen.findByRole("combobox", { name: "Result version" });
    expect(resultVersion).toHaveValue("run-2");
    expect(screen.getByText("Switch to view this document's output from another run.")).toBeInTheDocument();

    await user.selectOptions(resultVersion, "run-1");

    await waitFor(() => {
      const fieldCalls = listResources.mock.calls.filter(([url]) => url === "/fields/");
      expect(fieldCalls.at(-1)?.[1]).toMatchObject({ document: "document-1", run: "run-1" });
      expect(getDocument).toHaveBeenCalledWith("/documents/document-1/", { run: "run-1" }, expect.any(Object));
      expect(getDocument).toHaveBeenCalledWith("/documents/document-1/units/0/", { run: "run-1" }, expect.any(Object));
      expect(listResources).toHaveBeenCalledWith(
        "/labels/",
        expect.objectContaining({ document: "document-1", run: "run-1" }),
        expect.any(Object),
      );
    });
    expect(queryClient.getQueryState(["document", "document-1", "run-2"])).toBeDefined();
    expect(queryClient.getQueryState(["document", "document-1", "run-1"])).toBeDefined();
  });

  it("corrects a field through the accessible review dialog", async () => {
    const document = testDocument();
    const field = testField();
    getDocument.mockImplementation((url: string) =>
      Promise.resolve(url.includes("/units/") ? { kind: "page", index: 0, content: "Daniel Silva" } : document),
    );
    listResources.mockImplementation((url: string) => {
      if (url === "/run-items/") return Promise.resolve(page([testRunItem()]));
      if (url === "/runs/") return Promise.resolve(page([testRun()]));
      if (url === "/fields/") return Promise.resolve(page([field]));
      return Promise.resolve(page([]));
    });
    postResource.mockResolvedValue({ ...field, reviewed_value: "Danielle Silva", review_status: "corrected" });
    const { user } = renderWithApp(
      <Routes>
        <Route path="/review/:documentId" element={<ReviewPage />} />
      </Routes>,
      { route: "/review/document-1?run=run-1" },
    );

    await user.click(await screen.findByRole("button", { name: "Correct value" }));
    const value = await screen.findByRole("textbox", { name: "Corrected value" });
    await user.clear(value);
    await user.type(value, "Danielle Silva");
    await user.click(screen.getByRole("button", { name: "Save correction" }));

    await waitFor(() =>
      expect(postResource).toHaveBeenCalledWith("/fields/field-1/review/", {
        action: "correct",
        value: "Danielle Silva",
        reason: "Corrected in review workspace",
      }),
    );
    expect(successToast).toHaveBeenCalledWith("Field corrected");
  });

  it("advances to the next flagged field after a review action", async () => {
    const document = testDocument();
    const first = testField({ id: "field-1", name: "account_holder" });
    const second = testField({ id: "field-2", name: "routing_number", raw_value: "021000021" });
    let rows = [first, second];
    getDocument.mockImplementation((url: string) =>
      Promise.resolve(url.includes("/units/") ? { kind: "page", index: 0, content: "Daniel Silva" } : document),
    );
    listResources.mockImplementation((url: string, params: Record<string, string>) => {
      if (url === "/run-items/") return Promise.resolve(page([testRunItem()]));
      if (url === "/runs/") return Promise.resolve(page([testRun()]));
      if (url === "/fields/")
        return Promise.resolve(
          page(params.review_status ? rows.filter((field) => field.review_status === params.review_status) : rows),
        );
      return Promise.resolve(page([]));
    });
    postResource.mockImplementation(async () => {
      rows = [{ ...first, review_status: "accepted" }, second];
      return rows[0];
    });
    const { user } = renderWithApp(
      <Routes>
        <Route path="/review/:documentId" element={<ReviewPage />} />
      </Routes>,
      { route: "/review/document-1?run=run-1&field=field-1" },
    );

    await user.click((await screen.findAllByRole("button", { name: "Accept value" }))[0]);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /routing_number/ })).toHaveAttribute("aria-pressed", "true"),
    );
    expect(screen.getByText(/1 of 2 flagged fields reviewed/)).toBeInTheDocument();
  });

  it("requires and records a reason when a reviewer rejects a field", async () => {
    const document = testDocument();
    const field = testField();
    getDocument.mockImplementation((url: string) =>
      Promise.resolve(url.includes("/units/") ? { kind: "page", index: 0, content: "Daniel Silva" } : document),
    );
    listResources.mockImplementation((url: string) => {
      if (url === "/run-items/") return Promise.resolve(page([testRunItem()]));
      if (url === "/runs/") return Promise.resolve(page([testRun()]));
      if (url === "/fields/") return Promise.resolve(page([field]));
      return Promise.resolve(page([]));
    });
    postResource.mockResolvedValue({ ...field, review_status: "rejected" });
    const { user } = renderWithApp(
      <Routes>
        <Route path="/review/:documentId" element={<ReviewPage />} />
      </Routes>,
      { route: "/review/document-1?run=run-1" },
    );

    await user.click(await screen.findByRole("button", { name: "Reject result" }));
    const dialog = screen.getByRole("dialog", { name: "Reject field" });
    const reject = within(dialog).getByRole("button", { name: "Reject" });
    expect(reject).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/^Reason/), "The source does not support this value");
    await user.click(reject);

    await waitFor(() =>
      expect(postResource).toHaveBeenCalledWith("/fields/field-1/review/", {
        action: "reject",
        reason: "The source does not support this value",
      }),
    );
    expect(dialog).not.toHaveAttribute("open");
  });

  it("creates an explicit absent label and enforces the reviewer role", async () => {
    const document = testDocument();
    getDocument.mockImplementation((url: string) =>
      Promise.resolve(url.includes("/units/") ? { kind: "page", index: 0, content: "No account number" } : document),
    );
    listResources.mockImplementation((url: string) => {
      if (url === "/run-items/") return Promise.resolve(page([testRunItem()]));
      if (url === "/runs/") return Promise.resolve(page([testRun()]));
      return Promise.resolve(page([]));
    });
    postResource.mockResolvedValue(testLabel());
    const view = renderWithApp(
      <Routes>
        <Route path="/labeling/:documentId" element={<LabelPage />} />
      </Routes>,
      { route: "/labeling/document-1" },
    );

    await view.user.type(await screen.findByLabelText(/^Field name/), "account_number");
    await view.user.click(screen.getByRole("button", { name: "Mark absent" }));
    await waitFor(() =>
      expect(postResource).toHaveBeenCalledWith("/labels/", {
        document: "document-1",
        run: "run-1",
        mode: "absent",
        field_name: "account_number",
        notes: "",
      }),
    );

    view.unmount();
    session.roles = ["docai_viewers"];
    renderWithApp(
      <Routes>
        <Route path="/labeling/:documentId" element={<LabelPage />} />
      </Routes>,
      { route: "/labeling/document-1" },
    );
    expect(await screen.findByText("Creating ground truth requires the reviewer role.")).toBeInTheDocument();
  });
});
