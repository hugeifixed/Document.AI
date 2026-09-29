import { screen, waitFor, within } from "@testing-library/react";
import { renderWithApp } from "@/test/test-utils";
import type { PlaygroundSession } from "../types/playground";
import { WorkflowPlayground } from "./workflow-playground";

const api = vi.hoisted(() => ({
  listSessions: vi.fn(), getSession: vi.fn(), createSession: vi.fn(), deleteSession: vi.fn(),
  deleteSamples: vi.fn(), addDocument: vi.fn(), addSample: vi.fn(), generate: vi.fn(),
  saveProposal: vi.fn(), listDocuments: vi.fn(),
}));
vi.mock("../api/playground", () => api);
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const complete: PlaygroundSession = {
  id: "session-1", project: "project-1", expires_at: "2026-10-01T00:00:00Z", last_activity_at: "2026-09-28T12:00:00Z", status: "complete",
  goal: "Extract wages", workflow_type: "extract_structured", error_code: "", error_message: "",
  samples: [{ id: "sample-1", document_id: null, filename: "w2.txt", units: 1, source_kind: "temporary" }],
  proposal: {
    workflow_type: "extract_structured",
    documents: [{
      key: "w2", name: "Form W-2", description: "Wage statement", distinguishing_evidence: "",
      continuation_characteristics: "",
      fields: [{
        name: "wages_box1", description: "Box 1 wages", type: "currency", required: false,
        observed: true, sample_index: 0, unit: 1, source_label: "Wages", variable_rows: false,
        guidance: "", enum_values: [],
      }],
    }],
  },
  config: { mode: "custom", document_type: "w2", schema: { name: "w2", fields: [{ name: "wages_box1", type: "currency", required: false }] } },
  usage: { input_tokens: 200, cached_input_tokens: 100, output_tokens: 40 },
};

beforeEach(() => {
  Object.values(api).forEach((mock) => mock.mockReset());
  api.listSessions.mockResolvedValue([{ id: complete.id, status: "complete", goal: complete.goal, workflow_type: complete.workflow_type, expires_at: complete.expires_at, last_activity_at: complete.last_activity_at }]);
  api.getSession.mockResolvedValue(complete);
  api.saveProposal.mockImplementation(async (_id, proposal) => ({
    ...complete, proposal,
    config: { ...complete.config, schema: { name: "w2", fields: [{ name: proposal.documents[0].fields[0].name, required: proposal.documents[0].fields[0].required }] } },
  }));
});

it("resumes an operator proposal, edits fields and uses validated type-specific JSON", async () => {
  const onUse = vi.fn();
  const { user } = renderWithApp(<WorkflowPlayground projectId="project-1" datasetId={null} appliedKey={0} onUse={onUse} />);
  await user.click(screen.getByRole("button", { name: "Open assistant" }));
  await user.click(screen.getByText("Resume a proposal"));
  await user.click(await screen.findByRole("button", { name: /Extract wages complete/ }));
  expect(await screen.findByText(/Observed · sample 1, page\/sheet 1/)).toBeInTheDocument();
  await user.click(screen.getByText("wages_box1"));
  await user.click(screen.getByRole("checkbox", { name: "Required when extracted" }));
  await user.click(screen.getByRole("button", { name: "Use in builder" }));
  await waitFor(() => expect(api.saveProposal).toHaveBeenCalled());
  expect(api.saveProposal.mock.lastCall?.[1].documents[0].fields[0].required).toBe(true);
  await waitFor(() => expect(onUse).toHaveBeenCalledWith(
    "extract_structured",
    expect.objectContaining({ schema: expect.objectContaining({ fields: [expect.objectContaining({ required: true })] }) }),
  ));
});

it("deletes temporary samples without changing dataset documents", async () => {
  api.deleteSamples.mockResolvedValue({ ...complete, samples: [], proposal: {}, config: null, status: "ready" });
  const { user } = renderWithApp(<WorkflowPlayground projectId="project-1" datasetId={null} appliedKey={0} onUse={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Open assistant" }));
  await user.click(screen.getByText("Resume a proposal"));
  await user.click(await screen.findByRole("button", { name: /Extract wages complete/ }));
  await screen.findByText(/w2.txt/);
  await user.click(screen.getByRole("button", { name: "Clear examples" }));
  await user.click(within(screen.getByRole("dialog", { name: "Change examples?" })).getByRole("button", { name: "Change examples" }));
  await waitFor(() => expect(api.deleteSamples).toHaveBeenCalledWith(complete.id));
});

it("copies only the validated type-specific body", async () => {
  const { user } = renderWithApp(<WorkflowPlayground projectId="project-1" datasetId={null} appliedKey={0} onUse={vi.fn()} />);
  const copied = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
  await user.click(screen.getByRole("button", { name: "Open assistant" }));
  await user.click(screen.getByText("Resume a proposal"));
  await user.click(await screen.findByRole("button", { name: /Extract wages complete/ }));
  await screen.findByText(/Observed · sample 1, page\/sheet 1/);
  await user.click(screen.getByRole("button", { name: "Copy JSON" }));
  await waitFor(() => expect(copied).toHaveBeenCalled());
  const body = JSON.parse(copied.mock.calls[0][0]);
  expect(body.schema.fields[0].name).toBe("wages_box1");
  expect(body).not.toHaveProperty("model");
  expect(body).not.toHaveProperty("chunking");
});

it("keeps field edits when a proposal switch is cancelled", async () => {
  const second = { ...complete, id: "session-2", goal: "Another proposal" };
  api.listSessions.mockResolvedValue([
    { id: complete.id, status: complete.status, goal: complete.goal, workflow_type: complete.workflow_type, expires_at: complete.expires_at, last_activity_at: complete.last_activity_at },
    { id: second.id, status: second.status, goal: second.goal, workflow_type: second.workflow_type, expires_at: second.expires_at, last_activity_at: second.last_activity_at },
  ]);
  api.getSession.mockImplementation(async (id: string) => id === second.id ? second : complete);
  const { user } = renderWithApp(<WorkflowPlayground projectId="project-1" datasetId={null} appliedKey={0} onUse={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Open assistant" }));
  await user.click(screen.getByText("Resume a proposal"));
  await user.click(await screen.findByRole("button", { name: /Extract wages complete/ }));
  await user.click(await screen.findByText("wages_box1"));
  await user.clear(screen.getByRole("textbox", { name: "Field name" }));
  await user.type(screen.getByRole("textbox", { name: "Field name" }), "wages_amount");
  await user.click(screen.getByText("Resume a proposal"));
  await user.click(screen.getByRole("button", { name: /Another proposal complete/ }));
  expect(screen.getByRole("dialog", { name: "Discard proposal edits?" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("textbox", { name: "Field name" })).toHaveValue("wages_amount");
});

it("starts a fresh proposal without carrying over the previous goal or refinement", async () => {
  const fresh: PlaygroundSession = {
    ...complete, id: "session-new", status: "ready", goal: "", workflow_type: "",
    samples: [], proposal: {}, config: null,
  };
  api.createSession.mockResolvedValue(fresh);
  api.getSession.mockImplementation(async (id: string) => id === fresh.id ? fresh : complete);
  const { user } = renderWithApp(<WorkflowPlayground projectId="project-1" datasetId={null} appliedKey={0} onUse={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Open assistant" }));
  await user.click(screen.getByText("Resume a proposal"));
  await user.click(await screen.findByRole("button", { name: /Extract wages complete/ }));
  await user.type(screen.getByRole("textbox", { name: "Refine the proposal" }), "Add one field");
  await user.click(screen.getByRole("button", { name: "New proposal" }));
  await user.click(screen.getByRole("button", { name: "Switch proposal" }));
  await waitFor(() => expect(api.createSession).toHaveBeenCalled());
  expect(await screen.findByRole("textbox", { name: "What should this workflow do?" })).toHaveValue("");
  expect(screen.queryByRole("textbox", { name: "Refine the proposal" })).not.toBeInTheDocument();
});

it("marks a dataset document as selected and prevents adding it twice", async () => {
  const selected = {
    ...complete,
    status: "ready" as const, proposal: {}, config: null,
    samples: [...complete.samples, {
      id: "sample-2", document_id: "doc-1", filename: "loan.pdf", units: 2, source_kind: "dataset" as const,
    }],
  };
  api.listDocuments.mockResolvedValue({ results: [
    { id: "doc-1", original_filename: "loan.pdf", status: "validated" },
  ] });
  let finishAdd!: (value: PlaygroundSession) => void;
  api.addDocument.mockImplementation(() => new Promise<PlaygroundSession>((resolve) => { finishAdd = resolve; }));
  api.getSession.mockImplementation(async () => api.addDocument.mock.calls.length ? selected : complete);
  const { user } = renderWithApp(<WorkflowPlayground projectId="project-1" datasetId="dataset-1" appliedKey={0} onUse={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Open assistant" }));
  await user.click(screen.getByText("Resume a proposal"));
  await user.click(await screen.findByRole("button", { name: /Extract wages complete/ }));
  await user.click(screen.getByText("Choose a dataset document"));
  const add = await screen.findByRole("button", { name: /loan.pdf Add/ });
  await user.click(add);
  expect(api.addDocument).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog", { name: "Change examples?" })).toHaveTextContent("clears the current proposal");
  await user.click(within(screen.getByRole("dialog", { name: "Change examples?" })).getByRole("button", { name: "Cancel" }));
  expect(api.addDocument).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Use in builder" })).toBeInTheDocument();
  await user.click(add);
  await user.click(screen.getByRole("button", { name: "Change examples" }));
  await waitFor(() => expect(api.addDocument).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(add).toHaveFocus());
  expect(add).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByLabelText("Upload a private sample")).not.toBeDisabled();
  expect(screen.getByRole("button", { name: "Generate proposal" })).toHaveAttribute("aria-disabled", "true");
  await user.click(add);
  expect(api.addDocument).toHaveBeenCalledTimes(1);
  finishAdd(selected);
  const chosen = await screen.findByRole("button", { name: /loan.pdf Selected/ });
  expect(chosen).toHaveFocus();
  expect(chosen).toHaveAttribute("aria-disabled", "true");
  await user.click(chosen);
  expect(api.addDocument).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("list", { name: "Selected examples" })).toHaveTextContent("loan.pdf");
  expect(screen.queryByRole("button", { name: "Use in builder" })).not.toBeInTheDocument();
});

it("keeps the three-example limit stable without requesting a fourth document", async () => {
  api.getSession.mockResolvedValue({
    ...complete,
    samples: [
      ...complete.samples,
      { id: "sample-2", document_id: "doc-1", filename: "loan.pdf", units: 2, source_kind: "dataset" },
      { id: "sample-3", document_id: "doc-2", filename: "note.pdf", units: 1, source_kind: "dataset" },
    ],
  });
  api.listDocuments.mockResolvedValue({ results: [
    { id: "doc-3", original_filename: "next.pdf", status: "validated" },
  ] });
  const { user } = renderWithApp(<WorkflowPlayground projectId="project-1" datasetId="dataset-1" appliedKey={0} onUse={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Open assistant" }));
  await user.click(screen.getByText("Resume a proposal"));
  await user.click(await screen.findByRole("button", { name: /Extract wages complete/ }));
  await user.click(screen.getByText("Choose a dataset document"));

  expect(screen.getByLabelText("Upload a private sample")).toBeDisabled();
  expect(screen.getByText("3 of 3 examples selected. Clear examples to choose a different set.")).toBeInTheDocument();
  const fourth = await screen.findByRole("button", { name: /next.pdf Limit reached/ });
  expect(fourth).toHaveAttribute("aria-disabled", "true");
  await user.click(fourth);
  await user.click(fourth);
  expect(api.addDocument).not.toHaveBeenCalled();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("shows the actual processing stage and keeps inputs read-only", async () => {
  api.getSession.mockResolvedValue({ ...complete, status: "analyzing" });
  const { user } = renderWithApp(<WorkflowPlayground projectId="project-1" datasetId={null} appliedKey={0} onUse={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Open assistant" }));
  await user.click(screen.getByText("Resume a proposal"));
  await user.click(await screen.findByRole("button", { name: /Extract wages complete/ }));
  expect(await screen.findByRole("status")).toHaveTextContent("Checking the layout");
  expect(screen.getByRole("textbox", { name: "What should this workflow do?" })).toHaveAttribute("readonly");
  expect(screen.getByRole("radio", { name: "One form" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Generating…" })).toBeDisabled();
});
