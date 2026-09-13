import AxeBuilder from "@axe-core/playwright";
import { apiPage, DASHBOARD, DATASET, E2E_USER, fulfillApi, prepareWorkspace, PROJECT } from "./support/api";
import { expect, test } from "./support/test";

const message =
  "Input should be 'string', 'number', 'integer', 'date', 'boolean', 'currency', 'percent', 'identifier', 'enum' or 'list'";

for (const theme of ["light", "dark"] as const) {
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
    { width: 1440, height: 900 },
  ]) {
    test(`complete workflow validation report · ${theme} · ${viewport.width}`, async ({ page, apiGuard }, testInfo) => {
      await page.setViewportSize(viewport);
      await prepareWorkspace(page, E2E_USER.username, theme);
      let valid = false;
      await page.route("**/api/v1/**", async (route) => {
        const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
        if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
        if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
        if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
        if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
        if (path === `/projects/${PROJECT.id}/`) return fulfillApi(route, PROJECT);
        if (path === `/datasets/${DATASET.id}/`) return fulfillApi(route, DATASET);
        if (path === "/workflows/types/")
          return fulfillApi(route, {
            unbundle_classify_extract: { label: "Unbundle, classify and extract", schema: {} },
          });
        if (path === "/workflows/capabilities/")
          return fulfillApi(route, {
            image_normalization: { available: false, reason: "Disabled", profile: "adaptive-v1" },
            di_analysis: { ocr_high_resolution: false },
          });
        if (path === "/workflows/validate/") {
          if (valid) return fulfillApi(route, { valid: true, content_hash: "sha256:1234" });
          return route.fulfill({
            status: 422,
            json: {
              success: false,
              message: "The workflow configuration is invalid.",
              error_code: "WORKFLOW_CONFIG_ERROR",
              trace_id: "test-validation",
              errors: [26, 29, 33, 34, 35].map((index) => ({
                field: `config.schemas.0.fields.${index}.type`,
                message,
                code: "workflow_config_error",
              })),
            },
          });
        }
        return apiGuard.reject(route);
      });
      await page.goto("/workflows/new");
      await page.getByRole("button", { name: "Validate", exact: true }).click();
      const summary = page.locator("#workflow-validation-summary");
      await expect(summary).toHaveText("5 configuration issues");
      await expect(summary).toBeFocused();
      await page.getByRole("button", { name: "Close toast" }).click();
      await summary.focus();
      const list = page.getByRole("list", { name: "Configuration issues" });
      await expect(list.getByRole("listitem")).toHaveCount(5);
      await expect(list.getByText(message, { exact: true })).toHaveCount(5);
      await page.keyboard.press("Enter");
      await expect(list).not.toBeVisible();
      await page.keyboard.press("Space");
      await expect(list).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(await list.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
      await summary.scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath("validation.png"), fullPage: true });
      const editor = page.getByLabel("Type-specific configuration JSON");
      await editor.fill(`${await editor.inputValue()} `);
      await expect(summary).toHaveCount(0);
      valid = true;
      await page.getByRole("button", { name: "Validate", exact: true }).click();
      await expect(page.getByRole("button", { name: "Create version" })).toBeEnabled();
      await expect(editor).toHaveAttribute("aria-invalid", "false");
    });
  }
}
