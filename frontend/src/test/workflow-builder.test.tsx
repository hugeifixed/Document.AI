import { screen, waitFor } from "@testing-library/react";
import { WorkflowBuilder } from "@/pages/WorkflowBuilder";
import { renderWithApp } from "@/test/test-utils";

const { getWorkflowTypes, postWorkflow } = vi.hoisted(() => ({
  getWorkflowTypes: vi.fn(),
  postWorkflow: vi.fn(),
}));

vi.mock("@/auth/Session", () => ({
  useSession: () => ({ user: { roles: ["docai_operators"] } }),
}));
vi.mock("@/store/prefs", () => ({
  usePrefs: (selector: (state: { projectId: string }) => unknown) => selector({ projectId: "project-1" }),
}));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  get: getWorkflowTypes,
  post: postWorkflow,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderBuilder() {
  return renderWithApp(<WorkflowBuilder />);
}

describe("WorkflowBuilder", () => {
  beforeEach(() => {
    getWorkflowTypes.mockReset().mockResolvedValue({
      unbundle_classify_extract: { label: "Unbundle, classify and extract", schema: {} },
    });
    postWorkflow.mockReset().mockResolvedValue({ valid: true, content_hash: "sha256:1234567890abcdef1234" });
  });

  it("keeps invalid JSON out of the mutation error path", async () => {
    const { user } = renderBuilder();
    await waitFor(() => expect(screen.getByLabelText("Workflow type")).toBeEnabled());
    await user.type(screen.getByLabelText(/^Name/), "W-2 extraction");
    await user.clear(screen.getByLabelText("Type-specific configuration JSON"));
    await user.click(screen.getByLabelText("Type-specific configuration JSON"));
    await user.keyboard("{Shift>}[BracketLeft]{/Shift}");
    await user.click(screen.getByRole("button", { name: "Validate" }));

    expect(await screen.findByText(/Invalid JSON:/)).toHaveAttribute("id", "workflow-json-error");
    expect(postWorkflow).not.toHaveBeenCalled();
  });

  it("expires validation when any configuration field changes", async () => {
    const { user } = renderBuilder();
    await waitFor(() => expect(screen.getByLabelText("Workflow type")).toBeEnabled());
    await user.type(screen.getByLabelText(/^Name/), "W-2 extraction");
    await user.click(screen.getByRole("button", { name: "Validate" }));

    expect(await screen.findByText(/Valid · hash/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create version" })).toBeEnabled();
    await user.clear(screen.getByLabelText("Temperature"));
    await user.type(screen.getByLabelText("Temperature"), "0.5");

    expect(screen.queryByText(/Valid · hash/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create version" })).toBeDisabled();
  });
});
