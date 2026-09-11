import { act, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import type { Document, Page } from "@/api/types";
import { LabelPage, ReviewPage } from "@/pages/ReviewWorkspace";
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
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
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
        expect.objectContaining({ dataset: "dataset-1" }),
        expect.any(Object),
      ),
    );
    expect(queryClient.getQueryState(["runs", "dataset", "dataset-1"])).toBeDefined();
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

    await user.click(await screen.findByRole("button", { name: "Correct" }));
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
      <Routes><Route path="/review/:documentId" element={<ReviewPage />} /></Routes>,
      { route: "/review/document-1?run=run-1" },
    );

    await user.click(await screen.findByRole("button", { name: "Reject" }));
    const dialog = screen.getByRole("dialog", { name: "Reject field" });
    const reject = within(dialog).getByRole("button", { name: "Reject" });
    expect(reject).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/^Reason/), "The source does not support this value");
    await user.click(reject);

    await waitFor(() => expect(postResource).toHaveBeenCalledWith("/fields/field-1/review/", {
      action: "reject",
      reason: "The source does not support this value",
    }));
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
