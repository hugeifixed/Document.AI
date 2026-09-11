import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { Document, Page } from "@/api/types";
import { ReviewPage } from "@/pages/ReviewWorkspace";

const { getDocument, listResources } = vi.hoisted(() => ({
  getDocument: vi.fn(),
  listResources: vi.fn(),
}));

vi.mock("@/auth/Session", () => ({
  useSession: () => ({ user: { roles: ["docai_reviewers"] } }),
}));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  get: getDocument,
  list: listResources,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

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
  });

  it("loads document status in parallel and caches runs by dataset", async () => {
    let resolveDocument!: (document: Document) => void;
    getDocument.mockReturnValue(
      new Promise<Document>((resolve) => {
        resolveDocument = resolve;
      }),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/review/document-1"]}>
          <Routes>
            <Route path="/review/:documentId" element={<ReviewPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
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
});
