import AxeBuilder from "@axe-core/playwright";
import { apiPage, DASHBOARD, DATASET, E2E_USER, fulfillApi, prepareWorkspace, PROJECT } from "./support/api";
import { expect, test } from "./support/test";

const types = {
  unbundle_classify_extract: { label: "Unbundle, classify and extract", schema: {} },
  classify_structured: { label: "Classify structured documents", schema: {} },
  classify_unstructured: { label: "Classify unstructured documents", schema: {} },
  extract_structured: { label: "Extract structured documents", schema: {} },
  extract_unstructured: { label: "Extract unstructured documents", schema: {} },
  extract_template: { label: "Extract with a template", schema: {} },
};

for (const theme of ["light", "dark"] as const) {
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
    { width: 1440, height: 900 },
  ]) {
    test(`workflow help preserves the draft and keyboard focus · ${theme} · ${viewport.width}`, async ({
      page,
      apiGuard,
    }, testInfo) => {
      await page.setViewportSize(viewport);
      await prepareWorkspace(page, E2E_USER.username, theme);
      let validations = 0;
      await page.route("**/api/v1/**", async (route) => {
        const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
        if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
        if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
        if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
        if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
        if (path === `/projects/${PROJECT.id}/`) return fulfillApi(route, PROJECT);
        if (path === `/datasets/${DATASET.id}/`) return fulfillApi(route, DATASET);
        if (path === "/workflows/types/") return fulfillApi(route, types);
        if (path === "/workflows/capabilities/")
          return fulfillApi(route, {
            defaults: { azure_openai_deployment: "test-deployment" },
            image_normalization: { available: false, reason: "Disabled", profile: "adaptive-v1" },
            di_analysis: { ocr_high_resolution: false },
          });
        if (path === "/workflows/validate/") {
          validations += 1;
          expect(route.request().postDataJSON().config.chunking.strategy).toBe("semantic");
          expect(route.request().postDataJSON().config.model.max_tokens).toBe(16000);
          return fulfillApi(route, { valid: true, content_hash: "sha256:1234" });
        }
        return apiGuard.reject(route);
      });
      await page.goto("/workflows/new");
      await page.getByLabel("Name", { exact: true }).fill("Loan intake draft");
      await page.getByLabel("Strategy", { exact: true }).selectOption("semantic");
      const tokens = page.getByRole("spinbutton", { name: /Maximum output tokens/ });
      await expect(tokens).toHaveValue("4000");
      await tokens.fill("16000");
      await tokens.focus();
      await expect(tokens).toBeFocused();
      expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath("model-settings.png"), fullPage: true });
      const editor = page.getByLabel("Type-specific configuration JSON");
      const json = await editor.inputValue();
      await page.getByRole("button", { name: "Validate", exact: true }).click();
      await expect(page.getByRole("button", { name: "Create version", exact: true })).toBeEnabled();

      for (const [label, title] of [
        ["About workflow types", "Choose a workflow type"],
        ["About chunking", "Choose how to split content"],
      ]) {
        const trigger = page.getByRole("button", { name: label, exact: true });
        const box = await trigger.boundingBox();
        expect(box!.height).toBeGreaterThanOrEqual(viewport.width === 390 ? 44 : 40);
        expect(box!.width).toBeGreaterThanOrEqual(viewport.width === 390 ? 44 : 40);
        await trigger.focus();
        await page.keyboard.press("Enter");
        const dialog = page.getByRole("dialog", { name: title, exact: true });
        await expect(dialog.getByRole("heading", { name: title, exact: true })).toBeFocused();
        await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeInViewport();
        if (label === "About workflow types") {
          await expect(dialog.locator("dt")).toHaveCount(6);
          await expect(dialog.getByText(/For consistent W-2 boxes, use custom mode/)).toBeVisible();
        } else {
          await expect(dialog.locator("dt")).toHaveCount(7);
          await expect(dialog.getByText(/does not control how many files process at once/)).toBeVisible();
        }
        expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
        expect((await new AxeBuilder({ page }).include("dialog[open]").analyze()).violations).toEqual([]);
        await page.screenshot({ path: testInfo.outputPath(`${label}.png`) });
        await page.keyboard.press("Tab");
        await expect(dialog.getByRole("region", { name: `${title} guidance` })).toBeFocused();
        await page.keyboard.press("Tab");
        await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeFocused();
        // Native modal inertness prevents background form controls taking focus.
        await page.getByLabel("Name", { exact: true }).evaluate((el: HTMLInputElement) => el.focus());
        await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeFocused();
        if (label === "About workflow types") await page.keyboard.press("Escape");
        else await dialog.getByRole("button", { name: "Close", exact: true }).click();
        await expect(dialog).not.toBeVisible();
        await expect(trigger).toBeFocused();
      }

      expect(validations).toBe(1);
      await expect(page.getByLabel("Name", { exact: true })).toHaveValue("Loan intake draft");
      await expect(page.getByLabel("Strategy", { exact: true })).toHaveValue("semantic");
      await expect(editor).toHaveValue(json);
      await expect(page.getByRole("button", { name: "Create version", exact: true })).toBeEnabled();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.getByLabel("Workflow type", { exact: true }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath("help-controls.png") });

      await page.getByLabel("Workflow type", { exact: true }).selectOption("classify_structured");
      await page.getByRole("button", { name: "About chunking", exact: true }).click();
      await expect(
        page.getByRole("dialog").getByText(/Rule-based classification does not use these chunking settings/),
      ).toBeVisible();
    });
  }
}
