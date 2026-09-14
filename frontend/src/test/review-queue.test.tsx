import { screen, waitFor, within } from "@testing-library/react";
import type { Classification, ExtractedField } from "@/api/types";
import { ReviewQueue } from "@/pages/ReviewQueue";
import { renderWithApp } from "@/test/test-utils";

const { listFields, postBulk, preferences, workingContext } = vi.hoisted(() => ({
  listFields: vi.fn(),
  postBulk: vi.fn(),
  preferences: { pageSize: 25 },
  workingContext: { projectId: "project-1", datasetId: "dataset-1" },
}));

vi.mock("@/auth/Session", () => ({
  useSession: () => ({ user: { roles: ["docai_reviewers"] } }),
}));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  list: listFields,
  post: postBulk,
}));
vi.mock("@/store/prefs", () => ({
  usePrefs: (selector?: (state: typeof preferences) => unknown) => (selector ? selector(preferences) : preferences),
}));
vi.mock("@/workspace/context", () => ({
  useWorkingContext: (selector?: (state: typeof workingContext) => unknown) =>
    selector ? selector(workingContext) : workingContext,
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

function classification(): Classification {
  return {
    id: "classification-1",
    run: "run-1",
    document: "document-classification",
    document_name: "classification-only.pdf",
    segment: null,
    category: "other",
    reviewed_category: "",
    score: 0.2,
    method: "llm",
    rule_score: null,
    llm_evidence: "The document type was ambiguous.",
    review_status: "needs_review",
    spans: [],
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

  it("uses checkbox aliases in rows and selection labels while bulk review sends stored IDs", async () => {
    const checkbox = { ...field("checkbox-1"), name: "checkbox p1:sm2", raw_value: "unselected" };
    listFields.mockImplementation((url: string) =>
      Promise.resolve({
        count: url === "/fields/" ? 1 : 0,
        page: 1,
        page_size: 25,
        total_pages: 1,
        results: url === "/fields/" ? [checkbox] : [],
      }),
    );
    postBulk.mockResolvedValue({ applied: [checkbox.id], skipped: [] });
    const { user } = renderWithApp(<ReviewQueue />);
    const select = await screen.findByRole("checkbox", { name: "Select doc-checkbox-1 Checkbox 3 · Page 1" });
    expect(screen.getByRole("cell", { name: "Unchecked" })).toBeVisible();
    expect(screen.queryByText("checkbox p1:sm2")).not.toBeInTheDocument();
    await user.click(select);
    await user.click(screen.getByRole("button", { name: "Accept 1" }));
    await user.type(screen.getByLabelText("Type 1 to confirm"), "1");
    await user.click(screen.getByRole("button", { name: "Accept all" }));
    await waitFor(() =>
      expect(postBulk).toHaveBeenCalledWith("/fields/bulk-review/", {
        field_ids: ["checkbox-1"],
        action: "accept",
        confirm_count: 1,
        reason: "",
      }),
    );
  });

  it("summarizes structured values without letting raw JSON widen the queue", async () => {
    const structured = {
      ...field("list-1"),
      name: "state_and_local_entries",
      field_type: "list",
      raw_value: JSON.stringify([
        { state: "OH", state_wages: "40294.48" },
        { state: "KY", state_wages: "1240.00" },
      ]),
    };
    listFields.mockImplementation((url: string) =>
      Promise.resolve({
        count: url === "/fields/" ? 1 : 0,
        page: 1,
        page_size: 25,
        total_pages: 1,
        results: url === "/fields/" ? [structured] : [],
      }),
    );

    renderWithApp(<ReviewQueue />);

    const value = await screen.findByRole("link", { name: "2 entries" });
    expect(value).toHaveAttribute("href", "/review/document-list-1?run=run-1&field=list-1&from=review");
    expect(screen.queryByText(/state_wages/)).not.toBeInTheDocument();
  });

  it("clears page selections before a bulk action can target hidden rows", async () => {
    const { user } = renderWithApp(<ReviewQueue />);

    await user.click(await screen.findByRole("checkbox", { name: "Select doc-1 amount" }));
    expect(screen.getByRole("button", { name: "Accept 1" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));

    await screen.findByRole("checkbox", { name: "Select doc-2 amount" });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Accept 1" })).not.toBeInTheDocument());
    expect(postBulk).not.toHaveBeenCalled();
    expect(listFields).toHaveBeenCalledWith(
      "/fields/",
      expect.objectContaining({ project: "project-1", dataset: "dataset-1" }),
      expect.any(Object),
    );
  });

  it("requires an audit reason before rejecting selected fields", async () => {
    postBulk.mockResolvedValue({ applied: ["1"], skipped: [] });
    const { user } = renderWithApp(<ReviewQueue />);

    await user.click(await screen.findByRole("checkbox", { name: "Select doc-1 amount" }));
    await user.click(screen.getByRole("button", { name: "Reject 1" }));
    const dialog = screen.getByRole("dialog", { name: "Reject 1 field(s)" });
    const reject = within(dialog).getByRole("button", { name: "Reject all" });
    await user.type(within(dialog).getByLabelText("Type 1 to confirm"), "1");
    expect(reject).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/^Reason/), "Source document does not support this value");
    await user.click(reject);

    await waitFor(() =>
      expect(postBulk).toHaveBeenCalledWith("/fields/bulk-review/", {
        field_ids: ["1"],
        action: "reject",
        confirm_count: 1,
        reason: "Source document does not support this value",
      }),
    );
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
        reason: "",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows classification-only work instead of an empty review queue", async () => {
    listFields.mockImplementation((url: string) =>
      Promise.resolve(
        url === "/classifications/"
          ? { count: 1, page: 1, page_size: 25, total_pages: 1, results: [classification()] }
          : { count: 0, page: 1, page_size: 25, total_pages: 1, results: [] },
      ),
    );

    const { user } = renderWithApp(<ReviewQueue />);

    expect(await screen.findByRole("link", { name: "classification-only.pdf" })).toBeInTheDocument();
    expect(screen.getByText("other")).toBeInTheDocument();
    expect(listFields).toHaveBeenCalledWith(
      "/classifications/",
      expect.objectContaining({ project: "project-1", dataset: "dataset-1", review_status: "needs_review" }),
      expect.any(Object),
    );

    postBulk.mockResolvedValue({ ...classification(), review_status: "accepted", reviewed_category: "other" });
    await user.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() =>
      expect(postBulk).toHaveBeenCalledWith("/classifications/classification-1/accept/", {
        reason: "Accepted in review queue",
      }),
    );
  });

  it("corrects a queued classification with an auditable category decision", async () => {
    listFields.mockImplementation((url: string) =>
      Promise.resolve(
        url === "/classifications/"
          ? { count: 1, page: 1, page_size: 25, total_pages: 1, results: [classification()] }
          : url === "/categories/"
            ? {
                count: 1,
                page: 1,
                page_size: 25,
                total_pages: 1,
                results: [{ id: "category-1", project: "project-1", key: "agreement", name: "Agreement", version: 1 }],
              }
            : { count: 0, page: 1, page_size: 25, total_pages: 1, results: [] },
      ),
    );
    postBulk.mockResolvedValue({ ...classification(), review_status: "corrected", reviewed_category: "agreement" });
    const { user } = renderWithApp(<ReviewQueue />);

    await user.click(await screen.findByRole("button", { name: "Correct" }));
    const dialog = screen.getByRole("dialog", { name: "Correct document classification" });
    const category = within(dialog).getByLabelText(/^Correct category/);
    await user.clear(category);
    await user.type(category, "agreement");
    await user.type(within(dialog).getByLabelText("Review note (optional)"), "Document title confirms category");
    await user.click(within(dialog).getByRole("button", { name: "Save classification" }));

    await waitFor(() =>
      expect(postBulk).toHaveBeenCalledWith("/classifications/classification-1/reclassify/", {
        category: "agreement",
        reason: "Document title confirms category",
      }),
    );
  });
});
