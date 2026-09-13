import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { LabelPanel } from "@/components/review/LabelPanel";
import { useGroundTruthSelection } from "@/groundTruth/selection";
import { WorkflowBuilder } from "@/pages/WorkflowBuilder";
import { renderWithApp } from "@/test/test-utils";

const { registerDraft, getApi, postApi, navigate } = vi.hoisted(() => ({
  registerDraft: vi.fn(),
  getApi: vi.fn(),
  postApi: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock("@/workspace/navigation", () => ({ useWorkspaceDraft: registerDraft }));
vi.mock("@/auth/Session", () => ({
  useSession: () => ({ user: { roles: ["docai_operators", "docai_reviewers"] } }),
}));
vi.mock("@/workspace/context", () => ({
  useWorkingContext: (selector: (state: { projectId: string }) => unknown) => selector({ projectId: "project-1" }),
}));
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  get: getApi,
  post: postApi,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function LabelEditor({ mode = "cells" }: { mode?: "cells" | "words" | "pdf" }) {
  const [unit, setUnit] = useState(0);
  const selection = useGroundTruthSelection({
    documentId: "document-1",
    unit,
    fileFormat: mode === "cells" ? "xlsx" : "pdf",
    hasTextLayer: mode !== "words",
  });
  return (
    <>
      <button type="button" onClick={() => setUnit((current) => current + 1)}>
        Next sheet
      </button>
      <button type="button" onClick={() => selection.toggleWord("word-1")}>
        Pick word
      </button>
      <button
        type="button"
        onClick={() =>
          selection.capturePdfText({
            text: "Captured text",
            page: { left: 0, top: 0, width: 100 },
            rects: [{ left: 10, bottom: 20, width: 30, height: 10 }],
            pageWidth: 100,
            pageHeight: 100,
          })
        }
      >
        Select PDF text
      </button>
      <LabelPanel selection={selection} schemaFields={[]} labels={[]} />
    </>
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept;
    reject = fail;
  });
  return { promise, resolve, reject };
}

async function expectDraft(dirty: boolean, saving = false) {
  await waitFor(() => expect(registerDraft).toHaveBeenLastCalledWith(dirty, saving));
}

beforeEach(() => {
  registerDraft.mockReset();
  navigate.mockReset();
  postApi.mockReset();
  getApi
    .mockReset()
    .mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith("/capabilities/")
          ? { image_normalization: { available: true }, di_analysis: { ocr_high_resolution: true } }
          : { unbundle_classify_extract: { label: "Unbundle, classify and extract", schema: {} } },
      ),
    );
});

describe("workspace label drafts", () => {
  it("protects typed values and becomes clean when edits are reverted", async () => {
    const { user } = renderWithApp(<LabelEditor />);
    await expectDraft(false);
    await user.type(screen.getByLabelText(/^Field name/), "account_number");
    await expectDraft(true);
    await user.clear(screen.getByLabelText(/^Field name/));
    await expectDraft(false);
    await user.type(screen.getByLabelText("Notes"), "Check this value");
    await expectDraft(true);
  });

  it.each(["cells", "words", "pdf"] as const)("protects %s evidence without typed label fields", async (mode) => {
    const { user } = renderWithApp(<LabelEditor mode={mode} />);
    await expectDraft(false);
    if (mode === "cells") await user.type(screen.getByLabelText(/^Cell range/), "B3");
    else await user.click(screen.getByRole("button", { name: mode === "words" ? "Pick word" : "Select PDF text" }));
    await expectDraft(true);
    if (mode === "words") {
      await user.click(screen.getByRole("button", { name: "Pick word" }));
      await expectDraft(false);
    }
  });

  it("keeps failed saves dirty and resets form and evidence only after a successful retry", async () => {
    const first = deferred<unknown>();
    const retry = deferred<unknown>();
    postApi.mockReturnValueOnce(first.promise).mockReturnValueOnce(retry.promise);
    const { user } = renderWithApp(<LabelEditor />);
    await user.type(screen.getByLabelText(/^Field name/), "account_number");
    await user.type(screen.getByLabelText("Expected value"), "1234");
    await user.type(screen.getByLabelText("Notes"), "Verified");
    await user.type(screen.getByLabelText(/^Cell range/), "B3");
    await user.click(screen.getByRole("button", { name: "Save label" }));
    await expectDraft(true, true);
    await act(async () => first.reject(new Error("Could not save")));
    await expectDraft(true);
    expect(screen.getByLabelText("Expected value")).toHaveValue("1234");
    expect(screen.getByLabelText(/^Cell range/)).toHaveValue("B3");

    await user.click(screen.getByRole("button", { name: "Save label" }));
    await expectDraft(true, true);
    await act(async () => retry.resolve({ mapping_method: "exact", match_score: 1, mapping_exceptions: [] }));
    await expectDraft(false);
    expect(screen.getByLabelText(/^Field name/)).toHaveValue("account_number");
    expect(screen.getByLabelText("Notes")).toHaveValue("Verified");
    expect(screen.getByLabelText("Expected value")).toHaveValue("");
    expect(screen.getByLabelText(/^Cell range/)).toHaveValue("");
    await user.type(screen.getByLabelText("Expected value"), "5678");
    await expectDraft(true);
  });

  it("also establishes a clean baseline when marking a field absent", async () => {
    postApi.mockResolvedValue({});
    const { user } = renderWithApp(<LabelEditor mode="words" />);
    await user.type(screen.getByLabelText(/^Field name/), "account_number");
    await user.type(screen.getByLabelText("Notes"), "Not present");
    await user.click(screen.getByRole("button", { name: "Mark absent" }));
    await expectDraft(false);
    expect(postApi).toHaveBeenCalledWith("/labels/", expect.objectContaining({ mode: "absent", notes: "Not present" }));
  });

  it.each(["Field name", "Expected value", "Notes", "Cell range"])(
    "preserves %s changes made while a label is saving as an unsaved draft",
    async (label) => {
      const save = deferred<unknown>();
      postApi.mockReturnValue(save.promise);
      const { user } = renderWithApp(<LabelEditor />);
      await user.type(screen.getByLabelText(/^Field name/), "account_number");
      await user.type(screen.getByLabelText("Expected value"), "1234");
      await user.type(screen.getByLabelText("Notes"), "Submitted note");
      await user.type(screen.getByLabelText(/^Cell range/), "B3");
      await user.click(screen.getByRole("button", { name: "Save label" }));
      await expectDraft(true, true);
      const input = screen.getByLabelText(new RegExp(`^${label}`));
      await user.clear(input);
      const nextValue = label === "Cell range" ? "C4" : "Next draft";
      await user.type(input, nextValue);
      await act(async () => save.resolve({ mapping_method: "exact", match_score: 1, mapping_exceptions: [] }));
      expect(input).toHaveValue(nextValue);
      await expectDraft(true);
      expect(postApi).toHaveBeenCalledWith(
        "/labels/",
        expect.objectContaining({
          field_name: "account_number",
          expected_value: "1234",
          notes: "Submitted note",
          cell_range: "B3",
        }),
      );
    },
  );

  it("preserves the same cell range selected on another sheet while saving", async () => {
    const save = deferred<unknown>();
    postApi.mockReturnValue(save.promise);
    const { user } = renderWithApp(<LabelEditor />);
    await user.type(screen.getByLabelText(/^Field name/), "account_number");
    await user.type(screen.getByLabelText(/^Cell range/), "B3");
    await user.click(screen.getByRole("button", { name: "Save label" }));
    await expectDraft(true, true);
    await user.click(screen.getByRole("button", { name: "Next sheet" }));
    await user.type(screen.getByLabelText(/^Cell range/), "B3");
    await act(async () => save.resolve({ mapping_method: "exact", match_score: 1, mapping_exceptions: [] }));
    expect(screen.getByLabelText(/^Cell range/)).toHaveValue("B3");
    await expectDraft(true);
    expect(postApi).toHaveBeenCalledWith("/labels/", expect.objectContaining({ unit_index: 0, cell_range: "B3" }));
  });

  it("compares edits made during saving with the newly saved baseline", async () => {
    const save = deferred<unknown>();
    postApi.mockResolvedValueOnce({}).mockReturnValueOnce(save.promise);
    const { user } = renderWithApp(<LabelEditor mode="words" />);
    await user.type(screen.getByLabelText(/^Field name/), "account_number");
    await user.click(screen.getByRole("button", { name: "Mark absent" }));
    await expectDraft(false);
    await user.type(screen.getByLabelText("Notes"), "Submitted note");
    await user.click(screen.getByRole("button", { name: "Mark absent" }));
    await expectDraft(true, true);
    await user.clear(screen.getByLabelText("Notes"));
    await act(async () => save.resolve({}));
    expect(screen.getByLabelText("Notes")).toHaveValue("");
    await expectDraft(true);
  });

  it.each(["words", "pdf"] as const)("preserves new %s evidence captured during a label save", async (mode) => {
    const save = deferred<unknown>();
    postApi.mockReturnValue(save.promise);
    const { user } = renderWithApp(<LabelEditor mode={mode} />);
    await user.type(screen.getByLabelText(/^Field name/), "account_number");
    await user.click(screen.getByRole("button", { name: "Mark absent" }));
    await expectDraft(true, true);
    await user.click(screen.getByRole("button", { name: mode === "words" ? "Pick word" : "Select PDF text" }));
    await act(async () => save.resolve({}));
    await expectDraft(true);
    expect(screen.getByText(mode === "words" ? "1 word box(es) picked." : "Captured text")).toBeInTheDocument();
  });
});

describe("workspace configuration drafts", () => {
  it("tracks structured controls and separately controlled JSON, including reverting changes", async () => {
    const { user } = renderWithApp(<WorkflowBuilder />);
    await expectDraft(false);
    await user.type(screen.getByLabelText(/^Name/), "Statements");
    await expectDraft(true);
    await user.clear(screen.getByLabelText(/^Name/));
    await expectDraft(false);
    const json = screen.getByLabelText("Type-specific configuration JSON") as HTMLTextAreaElement;
    const original = json.value;
    fireEvent.change(json, { target: { value: "{}" } });
    await expectDraft(true);
    fireEvent.change(json, { target: { value: original } });
    await expectDraft(false);
    await user.click(screen.getByRole("checkbox", { name: /High-resolution OCR/ }));
    await expectDraft(true);
  });

  it("validation leaves a draft dirty and only successful creation clears it", async () => {
    const first = deferred<unknown>();
    const retry = deferred<unknown>();
    postApi
      .mockResolvedValueOnce({ valid: true, content_hash: "sha256:1234567890abcdef" })
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(retry.promise);
    const { user } = renderWithApp(<WorkflowBuilder />);
    await waitFor(() => expect(screen.getByLabelText("Workflow type")).toBeEnabled());
    await user.type(screen.getByLabelText(/^Name/), "Statements");
    fireEvent.change(screen.getByLabelText("Type-specific configuration JSON"), { target: { value: "{}" } });
    await user.click(screen.getByRole("button", { name: "Validate" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Create version" })).toBeEnabled());
    await expectDraft(true);
    await user.click(screen.getByRole("button", { name: "Create version" }));
    await expectDraft(true, true);
    expect(screen.getByLabelText(/^Name/)).toBeDisabled();
    expect(screen.getByLabelText("Workflow type")).toBeDisabled();
    expect(screen.getByLabelText("Type-specific configuration JSON")).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /High-resolution OCR/ })).toBeDisabled();
    await user.type(screen.getByLabelText(/^Name/), " changed during save");
    await user.type(screen.getByLabelText("Type-specific configuration JSON"), " changed during save");
    await act(async () => first.reject(new Error("Could not create")));
    await expectDraft(true);
    expect(screen.getByLabelText(/^Name/)).toBeEnabled();
    expect(screen.getByLabelText("Type-specific configuration JSON")).toBeEnabled();
    expect(screen.getByLabelText(/^Name/)).toHaveValue("Statements");
    expect(screen.getByLabelText("Type-specific configuration JSON")).toHaveValue("{}");

    await user.click(screen.getByRole("button", { name: "Create version" }));
    await expectDraft(true, true);
    await act(async () => retry.resolve({ id: "workflow-1", name: "Statements", version: 1 }));
    await expectDraft(false);
    expect(navigate).toHaveBeenCalledWith("/configurations?created=workflow-1");
  });
});
