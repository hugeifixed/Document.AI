import { screen, waitFor } from "@testing-library/react";
import { suggestWorkflowName, WorkflowBuilder } from "@/pages/WorkflowBuilder";
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

describe("workflow defaults", () => {
  beforeEach(() => {
    postWorkflow.mockReset().mockResolvedValue({ valid: true, content_hash: "sha256:1234" });
    getWorkflowTypes.mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith("/capabilities/")
          ? { defaults: { azure_openai_deployment: "institution-gpt52" } }
          : {
              unbundle_classify_extract: { label: "Unbundle, classify and extract", schema: {} },
              extract_structured: { label: "Extract structured", schema: {} },
            },
      ),
    );
  });
  it("uses the placeholder and environment deployment on creation while leaving the name editable", async () => {
    const { user } = renderBuilder();
    await waitFor(() => expect(screen.getByRole("button", { name: "Validate" })).toBeEnabled());
    const name = screen.getByLabelText("Name");
    expect(name).toHaveValue("");
    expect(name).toHaveAttribute("placeholder", "Form W-2 · Unbundle, classify and extract");
    expect(screen.getByLabelText("Azure OpenAI deployment")).toHaveValue("institution-gpt52");
    await user.click(screen.getByRole("button", { name: "Validate" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Create version" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Create version" }));
    await waitFor(() =>
      expect(postWorkflow).toHaveBeenLastCalledWith(
        "/workflows/",
        expect.objectContaining({
          name: "Form W-2 · Unbundle, classify and extract",
          config: expect.objectContaining({ model: expect.objectContaining({ deployment: "institution-gpt52" }) }),
        }),
      ),
    );
  });
  it("preserves user edits when defaults arrive late and the workflow type changes", async () => {
    let resolveDefaults!: (value: unknown) => void;
    const pending = new Promise((resolve) => {
      resolveDefaults = resolve;
    });
    getWorkflowTypes.mockImplementation((url: string) =>
      url.endsWith("/capabilities/")
        ? pending
        : Promise.resolve({
            unbundle_classify_extract: { label: "Unbundle", schema: {} },
            extract_structured: { label: "Extract structured", schema: {} },
          }),
    );
    const { user } = renderBuilder();
    const deployment = screen.getByLabelText("Azure OpenAI deployment");
    expect(deployment).toHaveValue("gpt-5.2");
    await user.clear(deployment);
    await user.type(deployment, " my-deployment ");
    await user.type(screen.getByLabelText("Name"), "My governed workflow");
    resolveDefaults({ defaults: { azure_openai_deployment: "late-default" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Validate" })).toBeEnabled());
    await user.selectOptions(screen.getByLabelText("Workflow type"), "extract_structured");
    expect(deployment).toHaveValue(" my-deployment ");
    expect(screen.getByLabelText("Name")).toHaveValue("My governed workflow");
    await user.click(screen.getByRole("button", { name: "Validate" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Create version" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Create version" }));
    await waitFor(() =>
      expect(postWorkflow).toHaveBeenLastCalledWith(
        "/workflows/",
        expect.objectContaining({
          name: "My governed workflow",
          config: expect.objectContaining({ model: expect.objectContaining({ deployment: "my-deployment" }) }),
        }),
      ),
    );
  });
  it("uses gpt-5.2 when the environment supplies no deployment", async () => {
    getWorkflowTypes.mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith("/capabilities/")
          ? { defaults: { azure_openai_deployment: "" } }
          : { unbundle_classify_extract: { label: "Unbundle", schema: {} } },
      ),
    );
    renderBuilder();
    await waitFor(() => expect(screen.getByRole("button", { name: "Validate" })).toBeEnabled());
    expect(screen.getByLabelText("Azure OpenAI deployment")).toHaveValue("gpt-5.2");
  });
  it("suggests stable, bounded names for single and mixed document types", () => {
    expect(
      suggestWorkflowName("extract_unstructured", '{"document_type":"promissory_note"}', "Extract unstructured"),
    ).toBe("promissory note · Extract unstructured");
    expect(suggestWorkflowName("classify_unstructured", '{"categories":[{},{}]}', "Classify")).toBe(
      "2 document types · Classify",
    );
    expect(suggestWorkflowName("extract_structured", "{broken")).toBe("Extract structured");
    expect(
      suggestWorkflowName("extract_structured", JSON.stringify({ schema: { name: "a".repeat(200) } }), "b".repeat(100)),
    ).toHaveLength(120);
  });
});
