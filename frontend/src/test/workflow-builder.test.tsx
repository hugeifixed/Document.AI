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
vi.mock("@/workspace/context", () => ({
  useWorkingContext: (selector: (state: { projectId: string }) => unknown) => selector({ projectId: "project-1" }),
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
    getWorkflowTypes.mockReset().mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith("/capabilities/")
          ? {
              image_normalization: { available: true, reason: "", profile: "adaptive-v1" },
              di_analysis: { ocr_high_resolution: true },
            }
          : { unbundle_classify_extract: { label: "Unbundle, classify and extract", schema: {} } },
      ),
    );
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
  it("snapshots independent scan options and expires validation after changing them", async () => {
    const { user } = renderBuilder();
    await user.type(screen.getByLabelText(/^Name/), "Scanned statements");
    const source = screen.getByLabelText("Processing source");
    expect(source).toHaveValue("off");
    expect(screen.queryByRole("checkbox", { name: /Skip confidently blank/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /High-resolution OCR/ }));
    await user.click(screen.getByRole("button", { name: "Validate" }));
    await waitFor(() =>
      expect(postWorkflow).toHaveBeenCalledWith(
        "/workflows/validate/",
        expect.objectContaining({
          config: expect.objectContaining({
            input_quality: { mode: "off", skip_blank_pages: false },
            di_analysis: { ocr_high_resolution: true },
          }),
        }),
      ),
    );
    await user.selectOptions(source, "adaptive");
    expect(screen.getByRole("button", { name: "Create version" })).toBeDisabled();
    const skip = screen.getByRole("checkbox", { name: /Skip confidently blank/ });
    expect(skip).not.toBeChecked();
    await user.click(skip);
    await user.click(screen.getByRole("button", { name: "Validate" }));
    await waitFor(() =>
      expect(postWorkflow).toHaveBeenLastCalledWith(
        "/workflows/validate/",
        expect.objectContaining({
          config: expect.objectContaining({ input_quality: { mode: "adaptive", skip_blank_pages: true } }),
        }),
      ),
    );
    await user.click(skip);
    expect(screen.getByRole("button", { name: "Create version" })).toBeDisabled();
    await user.selectOptions(source, "off");
    await user.click(screen.getByRole("button", { name: "Validate" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Create version" })).toBeEnabled());
    await user.click(screen.getByRole("checkbox", { name: /High-resolution OCR/ }));
    expect(screen.getByRole("button", { name: "Create version" })).toBeDisabled();
  });

  it("uses backend capability and keeps original processing available without enhancement", async () => {
    getWorkflowTypes.mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith("/capabilities/")
          ? {
              image_normalization: { available: false, reason: "Disabled by this deployment", profile: "adaptive-v1" },
              di_analysis: { ocr_high_resolution: false },
            }
          : { unbundle_classify_extract: { label: "Unbundle, classify and extract", schema: {} } },
      ),
    );
    const { user } = renderBuilder();
    expect(await screen.findByText("Disabled by this deployment")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Improve scanned pages" })).toBeDisabled();
    await user.type(screen.getByLabelText(/^Name/), "Original statements");
    await user.click(screen.getByRole("button", { name: "Validate" }));
    await waitFor(() => expect(postWorkflow).toHaveBeenCalledTimes(1));
    await user.clear(screen.getByLabelText("Type-specific configuration JSON"));
    await user.paste('{"input_quality":{"mode":"adaptive"}}');
    await user.click(screen.getByRole("button", { name: "Validate" }));
    expect(
      await screen.findByText("Use the scan enhancement and Document Intelligence controls for processing options."),
    ).toBeInTheDocument();
    expect(postWorkflow).toHaveBeenCalledTimes(1);
  });
});
