import { screen, waitFor, within } from "@testing-library/react";
import type { ExtractedField } from "@/api/types";
import { ReviewQueue } from "@/pages/ReviewQueue";
import { renderWithApp } from "@/test/test-utils";

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
    const { user } = renderWithApp(<ReviewQueue />);

    await user.click(await screen.findByRole("checkbox", { name: "Select doc-1 amount" }));
    expect(screen.getByRole("button", { name: "Accept 1" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));

    await screen.findByRole("checkbox", { name: "Select doc-2 amount" });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Accept 1" })).not.toBeInTheDocument());
    expect(postBulk).not.toHaveBeenCalled();
  });

  it("requires the selected count before applying a bulk review", async () => {
    postBulk.mockResolvedValue({ applied: ["1"], skipped: [] });
    const { user } = renderWithApp(<ReviewQueue />);

    await user.click(await screen.findByRole("checkbox", { name: "Select doc-1 amount" }));
    await user.click(screen.getByRole("button", { name: "Accept 1" }));
    const dialog = screen.getByRole("dialog", { name: "Accept 1 field(s)" });
    const confirm = screen.getByRole("button", { name: "Accept all" });
    expect(confirm).toBeDisabled();

    await user.type(within(dialog).getByLabelText("Type 1 to confirm"), "1");
    await user.click(confirm);

    await waitFor(() =>
      expect(postBulk).toHaveBeenCalledWith("/fields/bulk-review/", {
        field_ids: ["1"],
        action: "accept",
        confirm_count: 1,
        reason: "bulk from queue",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
