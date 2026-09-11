import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ExtractedField } from "@/api/types";
import { ReviewQueue } from "@/pages/ReviewQueue";

const { listFields, postBulk } = vi.hoisted(() => ({ listFields: vi.fn(), postBulk: vi.fn() }));

vi.mock("@/auth/Session", () => ({
  useSession: () => ({ user: { roles: ["docai_reviewers"] } }),
}));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  list: listFields,
  post: postBulk,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function field(id: string): ExtractedField {
  return {
    id,
    run: "run-1",
    document: `document-${id}`,
    document_name: `doc-${id}`,
    segment: null,
    name: "amount",
    field_type: "currency",
    raw_value: "$10",
    normalized_value: "10",
    reviewed_value: null,
    score: 0.7,
    source_text: "$10",
    method: "llm",
    strategy: "whole_document",
    fallback_used: "",
    model_deployment: "model",
    prompt: null,
    schema: null,
    validation_status: "valid",
    validation_messages: [],
    suggested_correction: null,
    review_status: "needs_review",
    grounded: true,
    spans: [],
    modified: "2026-09-11T00:00:00Z",
  };
}

describe("ReviewQueue", () => {
  beforeEach(() => {
    postBulk.mockReset();
    listFields.mockReset().mockImplementation((_url: string, params: { page: number }) => {
      const page = params.page ?? 1;
      return Promise.resolve({ count: 2, page, page_size: 25, total_pages: 2, results: [field(String(page))] });
    });
  });

  it("clears page selections before a bulk action can target hidden rows", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ReviewQueue />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select doc-1 amount" }));
    expect(screen.getByRole("button", { name: "Accept 1" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await screen.findByRole("checkbox", { name: "Select doc-2 amount" });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Accept 1" })).not.toBeInTheDocument());
    expect(postBulk).not.toHaveBeenCalled();
  });
});
