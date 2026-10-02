import AxeBuilder from "@axe-core/playwright";
import { apiPage, DASHBOARD, DATASET, E2E_USER, fulfillApi, prepareWorkspace, PROJECT } from "./support/api";
import { expect, test } from "./support/test";

const id = "8df844e3-fbdc-4fb1-a364-061143c36c42";
const config = {
  mode: "custom", document_type: "w2",
  schema: { name: "w2", fields: [{ name: "wages_box1", type: "currency", required: false, description: "Box 1 wages" }] },
  routing: [{ when: {}, outcome: "human_review" }],
};
const proposal = {
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
};
const session = {
  id, project: PROJECT.id, expires_at: "2026-10-01T00:00:00Z", last_activity_at: "2026-09-28T12:00:00Z", status: "complete",
  goal: "bank_loan_boarding_data_sheet_document_capturing_all_printed_fields_and_servicing_terms",
  workflow_type: "extract_structured", error_code: "", error_message: "",
  samples: [{ id: "sample-1", document_id: null, filename: "w2.txt", units: 1, source_kind: "temporary" }],
  proposal, config, usage: { input_tokens: 100, cached_input_tokens: 20, output_tokens: 40 },
};
const types = {
  unbundle_classify_extract: { label: "Unbundle, classify and extract", schema: {} },
  extract_structured: { label: "Extract structured documents", schema: {} },
  extract_unstructured: { label: "Extract unstructured documents", schema: {} },
};

for (const [theme, viewport] of [
  ["light", { width: 390, height: 844 }],
  ["light", { width: 768, height: 1024 }],
  ["dark", { width: 1024, height: 768 }],
  ["dark", { width: 1440, height: 900 }],
] as const) {
  test(`workflow playground preserves unsaved changes and validates a proposal · ${theme} · ${viewport.width}`, async ({ page, apiGuard }) => {
    await page.setViewportSize(viewport);
    await prepareWorkspace(page, E2E_USER.username, theme);
    let validations = 0;
    let sessionResult = session;
    await page.route("**/api/v1/**", async (route) => {
      const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
      if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
      if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
      if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
      if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
      if (path === `/projects/${PROJECT.id}/`) return fulfillApi(route, PROJECT);
      if (path === `/datasets/${DATASET.id}/`) return fulfillApi(route, DATASET);
      if (path === "/workflows/types/") return fulfillApi(route, types);
      if (path === "/workflows/capabilities/") return fulfillApi(route, {
        defaults: { azure_openai_deployment: "test-deployment" },
        image_normalization: { available: false, reason: "Disabled", profile: "adaptive-v1" },
        di_analysis: { ocr_high_resolution: false },
      });
      if (path === "/workflow-playground/sessions/") return fulfillApi(route, [{
        id, status: "complete", goal: session.goal, workflow_type: session.workflow_type, expires_at: session.expires_at, last_activity_at: session.last_activity_at,
      }]);
      if (path === `/workflow-playground/sessions/${id}/`) return fulfillApi(route, sessionResult);
      if (path === `/workflow-playground/sessions/${id}/proposal/`) return fulfillApi(route, sessionResult);
      if (path === `/workflow-playground/sessions/${id}/documents/`) {
        sessionResult = { ...session, samples: [...session.samples, {
          id: "sample-2", document_id: "doc-1", filename: "loan_boarding_example.pdf", units: 2, source_kind: "dataset",
        }] };
        return fulfillApi(route, sessionResult);
      }
      if (path === "/documents/") return fulfillApi(route, apiPage([{
        id: "doc-1", original_filename: "loan_boarding_example.pdf", status: "validated",
      }]));
      if (path === "/workflows/validate/") {
        validations += 1;
        expect(route.request().postDataJSON().workflow_type).toBe("extract_structured");
        return fulfillApi(route, { valid: true, content_hash: "sha256:1234" });
      }
      return apiGuard.reject(route);
    });
    await page.goto("/workflows/new");
    const editor = page.getByLabel("Type-specific configuration JSON");
    const original = await editor.inputValue();
    await page.getByLabel("Name", { exact: true }).fill("My unsaved workflow");
    await page.getByRole("button", { name: "Open assistant" }).click();
    await page.getByText("Resume a proposal").click();
    await page.getByRole("button", { name: /bank_loan_boarding.*complete/ }).click();
    await expect(page.getByText(/Observed · sample 1, page\/sheet 1/)).toBeVisible();
    await page.getByText("Choose a dataset document").click();
    await expect(page.getByPlaceholder("Search by file name")).toBeVisible();
    await page.getByRole("button", { name: /loan_boarding_example.pdf Add/ }).click();
    const selectedDocument = page.getByRole("button", { name: /loan_boarding_example.pdf Selected/ });
    await expect(selectedDocument).toHaveAttribute("aria-disabled", "true");
    await expect(selectedDocument).toBeFocused();
    await expect(page.getByLabel("Upload a private sample")).toBeEnabled();
    await expect(page.getByRole("button", { name: "Generate proposal" })).toBeEnabled();
    await selectedDocument.dispatchEvent("click");
    await expect(page.getByRole("list", { name: "Selected examples" }).getByText("loan_boarding_example.pdf")).toHaveCount(1);
    expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("button", { name: "Use in builder" }).click();
    const dialog = page.getByRole("dialog", { name: "Replace builder content?" });
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(editor).toHaveValue(original);
    await page.getByRole("button", { name: "Use in builder" }).click();
    await dialog.getByRole("button", { name: "Use proposal" }).click();
    await expect(page.getByLabel("Workflow type", { exact: true })).toHaveValue("extract_structured");
    await expect(editor).toHaveValue(/wages_box1/);
    await expect.poll(() => validations).toBe(1);
    await expect(page.getByRole("button", { name: "Create version" })).toBeEnabled();

    sessionResult = { ...sessionResult, status: "analyzing" };
    await page.reload();
    await page.getByRole("button", { name: "Open assistant" }).click();
    await page.getByText("Resume a proposal").click();
    await page.getByRole("button", { name: /bank_loan_boarding.*complete/ }).click();
    await expect(page.getByRole("status")).toContainText("Checking the layout");
    await expect(page.getByRole("textbox", { name: "What should this workflow do?" })).toHaveAttribute("readonly");
    await expect(page.getByRole("radio", { name: "One form" })).toBeDisabled();
    expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
  });
}
