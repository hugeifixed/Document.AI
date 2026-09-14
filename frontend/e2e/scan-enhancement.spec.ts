import AxeBuilder from "@axe-core/playwright";
import { Buffer } from "node:buffer";
import {
  apiPage,
  DASHBOARD,
  DATASET,
  DOCUMENT,
  E2E_USER,
  fulfillApi,
  prepareWorkspace,
  PROJECT,
  RUN,
  runProgress,
  WORKFLOW,
} from "./support/api";
import { expect, test } from "./support/test";

// Minimal valid synthetic PDF: a real PDF.js canvas without personal data or binary fixture files.
function blankPdf() {
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Contents 4 0 R >>",
    "<< /Length 0 >>\nstream\n\nendstream",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xref = Buffer.byteLength(pdf);
  pdf += `xref\n0 5\n0000000000 65535 f \n${offsets
    .slice(1)
    .map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`)
    .join("")}trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(pdf);
}

const quality = {
  mode: "adaptive",
  status: "fallback",
  profile: "adaptive-v1",
  pages_examined: 4,
  pages_adjusted: 3,
  pages_skipped: 0,
  duration_ms: 120,
  warnings: [
    {
      code: "NORMALIZATION_FALLBACK",
      message:
        "Scan enhancement could not be completed for page 4 because the processing limit was reached. Processing continued with the original page, and its text remains available for review.",
      pages: [4],
      retryable: false,
    },
  ],
};
const item = {
  id: "item-1",
  run: RUN.id,
  document: DOCUMENT.id,
  document_name: "scanned-statement.png",
  status: "succeeded",
  stage: "complete",
  attempts: 1,
  error_code: "",
  error_message: "",
  retryable: false,
  duration_ms: 250,
  correlation_id: "e2e",
  modified: RUN.created,
  input_quality: quality,
};
const workflow = {
  ...WORKFLOW,
  config: { input_quality: { mode: "adaptive", skip_blank_pages: false }, di_analysis: { ocr_high_resolution: false } },
};
const completedRun = { ...RUN, status: "succeeded", processed_items: 1, stage: "complete" };

for (const theme of ["light", "dark"] as const) {
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
    { width: 1440, height: 900 },
  ]) {
    test(`scan options, warnings and source isolation · ${theme} · ${viewport.width}`, async ({
      page,
      apiGuard,
    }, testInfo) => {
      test.setTimeout(90_000);
      await page.setViewportSize(viewport);
      await prepareWorkspace(page, E2E_USER.username, theme);
      const scopedRequests: string[] = [];
      let submitted: unknown;
      await page.route("**/api/v1/**", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const path = url.pathname.replace("/api/v1", "");
        const run = url.searchParams.get("run");
        if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
        if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
        if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
        if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
        if (path === `/datasets/${DATASET.id}/` && request.method() === "GET") return fulfillApi(route, DATASET);
        if (path === `/projects/${PROJECT.id}/` && request.method() === "GET") return fulfillApi(route, PROJECT);
        if (path === "/workflows/types/")
          return fulfillApi(route, {
            extract_structured: { label: "Extract structured", schema: {} },
            unbundle_classify_extract: { label: "Unbundle, classify and extract", schema: {} },
          });
        if (path === "/workflows/capabilities/")
          return fulfillApi(route, {
            defaults: { azure_openai_deployment: "institution-gpt52" },
            image_normalization: { available: true, reason: "", profile: "adaptive-v1" },
            di_analysis: { ocr_high_resolution: true },
          });
        if (path === "/workflows/validate/") {
          submitted = request.postDataJSON();
          return fulfillApi(route, { valid: true, content_hash: "sha256:abcdef1234567" });
        }
        if (path === "/workflows/") return fulfillApi(route, apiPage([workflow]));
        if (path === "/runs/")
          return fulfillApi(route, apiPage([completedRun, { ...completedRun, id: "run-2", name: "Original run" }]));
        if (path === `/runs/${RUN.id}/`) return fulfillApi(route, completedRun);
        if (path === `/runs/${completedRun.id}/progress/`) return fulfillApi(route, runProgress(completedRun));
        if (path === `/runs/${RUN.id}/usage/`) return fulfillApi(route, { calls: 0, by_item: [] });
        if (path === "/run-items/")
          return fulfillApi(route, apiPage([item, { ...item, id: "item-2", run: "run-2", input_quality: {} }]));
        if (path === "/fields/") return fulfillApi(route, apiPage([]));
        if (path === "/labels/") {
          scopedRequests.push(`labels:${run}`);
          return fulfillApi(route, apiPage([]));
        }
        if (path === `/documents/${DOCUMENT.id}/`) {
          scopedRequests.push(`document:${run}`);
          return fulfillApi(route, {
            ...DOCUMENT,
            original_filename: "scanned-statement.png",
            file_format: "png",
            processing_source: {
              url: `/api/v1/documents/${DOCUMENT.id}/${run === "run-2" ? "original/" : "processing-source/?run=run-1"}`,
              file_format: run === "run-2" ? "png" : "pdf",
              is_original: run === "run-2",
              layout_artifact: `layout-${run}`,
            },
          });
        }
        if (path === `/documents/${DOCUMENT.id}/units/0/`) {
          scopedRequests.push(`unit:${run}`);
          return fulfillApi(route, {
            kind: "page",
            index: 0,
            width: 300,
            height: 400,
            has_text_layer: false,
            content: "Account",
            words: [
              {
                id: `${run}:w1`,
                text: run === "run-2" ? "Original account" : "Account",
                polygon: [0.1, 0.1, 0.3, 0.1, 0.3, 0.2, 0.1, 0.2],
              },
            ],
          });
        }
        if (path === `/documents/${DOCUMENT.id}/processing-source/`) {
          scopedRequests.push(`source:${run}`);
          return route.fulfill({ contentType: "application/pdf", body: blankPdf() });
        }
        if (path === `/documents/${DOCUMENT.id}/original/`)
          return route.fulfill({
            contentType: "image/png",
            body: Buffer.from(
              "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==",
              "base64",
            ),
          });
        return apiGuard.reject(route);
      });
      const noOverflow = async () =>
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.goto("/workflows/new");
      await expect(page.locator("html")).toHaveAttribute("data-theme", `extract-${theme}`);
      await expect(page.getByLabel("Name", { exact: true })).toHaveAttribute(
        "placeholder",
        "Form W-2 · Unbundle, classify and extract",
      );
      await expect(page.getByLabel("Azure OpenAI deployment")).toHaveValue("institution-gpt52");
      await page.getByLabel("Processing source").selectOption("adaptive");
      const skip = page.getByRole("checkbox", { name: /Skip confidently blank pages/ });
      await expect(skip).not.toBeChecked();
      await skip.focus();
      await page.keyboard.press("Space");
      await expect(skip).toBeChecked();
      await page.getByRole("button", { name: "Validate", exact: true }).click();
      await expect
        .poll(() => submitted)
        .toMatchObject({
          config: {
            model: { deployment: "institution-gpt52" },
            input_quality: { mode: "adaptive", skip_blank_pages: true },
            di_analysis: { ocr_high_resolution: false },
          },
        });
      await expect(page.getByRole("button", { name: "Create version" })).toBeEnabled();
      await page.getByRole("checkbox", { name: /High-resolution OCR/ }).check();
      await expect(page.getByRole("button", { name: "Create version" })).toBeDisabled();
      await noOverflow();
      expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
      await page.evaluate(() => scrollTo(0, 0));
      await page.screenshot({ path: testInfo.outputPath("workflow.png"), fullPage: true });

      await page.goto("/runs");
      await expect(page.getByText("Scan enhancement: Improve scanned pages")).toBeVisible();
      await noOverflow();
      await page.goto(`/runs/${RUN.id}`);
      await expect(page.getByText("3 pages adjusted")).toBeVisible();
      const details = page.getByRole("button", { name: /Scan details for/ });
      const rowHeight = await details.evaluate((element) => element.closest("tr")!.getBoundingClientRect().height);
      await details.focus();
      await page.keyboard.press("Enter");
      const dialog = page.getByRole("dialog", { name: "Scan details" });
      await expect(dialog).toBeVisible();
      await expect
        .poll(() => details.evaluate((element) => element.closest("tr")!.getBoundingClientRect().height))
        .toBe(rowHeight);
      await expect(page.getByText(quality.warnings[0].message)).toBeVisible();
      await noOverflow();
      expect((await new AxeBuilder({ page }).include("dialog[open]").analyze()).violations).toEqual([]);
      await page.evaluate(() => scrollTo(0, 0));
      await page.screenshot({ path: testInfo.outputPath("warning.png"), fullPage: true });
      await page.keyboard.press("Escape");
      await expect(dialog).not.toBeVisible();
      await expect(details).toBeFocused();
      await details.click();
      await dialog.getByRole("button", { name: "Close", exact: true }).click();
      await expect(dialog).not.toBeVisible();
      await expect(details).toBeFocused();

      await page.goto(`/labeling/${DOCUMENT.id}?run=run-1`);
      await expect(page.locator(".react-pdf__Page canvas")).toBeVisible();
      const word = page.getByRole("button", { name: "word Account", exact: true });
      await word.focus();
      await page.keyboard.press("Space");
      await expect(word).toHaveAttribute("aria-pressed", "true");
      await expect(page.locator(".react-pdf__Page__textContent")).toHaveCount(0);
      await noOverflow();
      await page.evaluate(() => scrollTo(0, 0));
      await page.screenshot({ path: testInfo.outputPath("processing-source.png"), fullPage: true });
      await page.getByRole("button", { name: "View original", exact: true }).click();
      await expect(word).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Save label" })).toHaveCount(0);
      await expect(page.getByRole("img", { name: "scanned-statement.png, page 1" })).toBeVisible();
      await page.getByRole("button", { name: "View processing source" }).click();
      await expect(page.locator(".react-pdf__Page canvas")).toBeVisible();
      await page.getByRole("combobox", { name: "Result version" }).selectOption("run-2");
      await expect(page.getByRole("button", { name: "word Original account" })).toHaveAttribute(
        "aria-pressed",
        "false",
      );
      await expect(page.getByRole("button", { name: "View original", exact: true })).toHaveCount(0);
      expect(scopedRequests).toEqual(
        expect.arrayContaining([
          "document:run-1",
          "unit:run-1",
          "labels:run-1",
          "source:run-1",
          "document:run-2",
          "unit:run-2",
          "labels:run-2",
        ]),
      );
      await noOverflow();
      expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
      await page.evaluate(() => scrollTo(0, 0));
      await page.screenshot({ path: testInfo.outputPath("source-switch.png"), fullPage: true });
    });
  }
}
