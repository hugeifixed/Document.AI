import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { WorkflowBuilder } from "@/pages/WorkflowBuilder";

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
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <WorkflowBuilder />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("WorkflowBuilder", () => {
  beforeEach(() => {
    getWorkflowTypes.mockReset().mockResolvedValue({
      unbundle_classify_extract: { label: "Unbundle, classify and extract", schema: {} },
    });
    postWorkflow.mockReset().mockResolvedValue({ valid: true, content_hash: "sha256:1234567890abcdef1234" });
  });

  it("keeps invalid JSON out of the mutation error path", async () => {
    renderBuilder();
    await waitFor(() => expect(screen.getByLabelText("Workflow type")).toBeEnabled());
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "W-2 extraction" } });
    fireEvent.change(screen.getByLabelText("Type-specific configuration JSON"), { target: { value: "{" } });
    fireEvent.click(screen.getByRole("button", { name: "Validate" }));

    expect(await screen.findByText(/Invalid JSON:/)).toHaveAttribute("id", "workflow-json-error");
    expect(postWorkflow).not.toHaveBeenCalled();
  });

  it("expires validation when any configuration field changes", async () => {
    renderBuilder();
    await waitFor(() => expect(screen.getByLabelText("Workflow type")).toBeEnabled());
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "W-2 extraction" } });
    fireEvent.click(screen.getByRole("button", { name: "Validate" }));

    expect(await screen.findByText(/Valid · hash/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create version" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "0.5" } });

    expect(screen.queryByText(/Valid · hash/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create version" })).toBeDisabled();
  });
});
