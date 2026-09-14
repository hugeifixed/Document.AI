import AxeBuilder from "@axe-core/playwright";
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

for (const theme of ["light", "dark"] as const) {
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
    { width: 1440, height: 900 },
  ]) {
    test(`choose a precise run scope · ${theme} · ${viewport.width}`, async ({ page, apiGuard }, testInfo) => {
      await page.setViewportSize(viewport);
      await prepareWorkspace(page, E2E_USER.username, theme);
      const first = {
        ...DOCUMENT,
        original_filename:
          "W2_Annual_statement_with_a_very_long_filename_for_the_selected_dataset_and_reporting_period_2026.pdf",
        file_format: "pdf",
        size_bytes: 102400,
        status: "validated",
      };
      const second = { ...first, id: "doc-2", original_filename: "Quarterly-statement.pdf", status: "failed" };
      const firstPage = [
        first,
        ...Array.from({ length: 24 }, (_, index) => ({
          ...first,
          id: `archive-${index}`,
          original_filename: `Archive-statement-${index + 1}.pdf`,
          status: "processed",
        })),
      ];
      const run = { ...RUN, status: "queued", total_items: 2, processed_items: 0 };
      let submitted: Record<string, unknown> | undefined;
      const listRequests: URL[] = [];
      await page.route("**/api/v1/**", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const path = url.pathname.replace("/api/v1", "");
        if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
        if (path === "/dashboard/")
          return fulfillApi(route, {
            ...DASHBOARD,
            guidance: {
              ...DASHBOARD.guidance,
              documents: { ...DASHBOARD.guidance.documents, total: 26, runnable: 26 },
            },
          });
        if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
        if (path === "/datasets/") return fulfillApi(route, apiPage([{ ...DATASET, document_count: 26 }]));
        if (path === "/workflows/") return fulfillApi(route, apiPage([WORKFLOW]));
        if (path === "/documents/") {
          listRequests.push(url);
          const number = Number(url.searchParams.get("page") || 1);
          const searching = !!url.searchParams.get("search");
          return fulfillApi(route, {
            ...apiPage(number === 2 || searching ? [second] : firstPage),
            page: number,
            count: searching ? 1 : 26,
            total_pages: searching ? 1 : 2,
          });
        }
        if (path === "/runs/" && request.method() === "POST") {
          submitted = request.postDataJSON();
          return fulfillApi(route, run, 201);
        }
        if (path === "/runs/") return fulfillApi(route, apiPage([]));
        if (path === `/runs/${RUN.id}/`) return fulfillApi(route, run);
        if (path === `/runs/${run.id}/progress/`) return fulfillApi(route, runProgress(run));
        if (path === `/runs/${RUN.id}/usage/`) return fulfillApi(route, { calls: 0, by_item: [] });
        if (path === "/run-items/") return fulfillApi(route, apiPage([]));
        return apiGuard.reject(route);
      });
      await page.goto("/runs");
      const scope = page.getByRole("group", { name: "Documents to process" });
      await expect(page.getByLabel("Run name")).toHaveValue(new RegExp(`${WORKFLOW.name} v${WORKFLOW.version}`));
      await expect(page.getByLabel("Run name")).toHaveAttribute("maxlength", "160");
      expect((await new AxeBuilder({ page }).include("form").analyze()).violations).toEqual([]);
      const trigger = scope.getByRole("button", { name: "Choose documents", exact: true });
      await expect(trigger).toBeEnabled();
      const limit = scope.getByLabel("Document limit");
      await expect(limit).toHaveAccessibleDescription(/Blank includes all eligible documents/);
      await limit.fill("5");
      const limitBox = await limit.boundingBox();
      const triggerBox = await trigger.boundingBox();
      if (viewport.width >= 640) expect(Math.abs(limitBox!.y - triggerBox!.y)).toBeLessThanOrEqual(1);
      else expect(triggerBox!.y).toBeGreaterThan(limitBox!.y + limitBox!.height);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath("run-document-controls.png") });
      await trigger.focus();
      await page.keyboard.press("Enter");
      const dialog = page.getByRole("dialog", { name: "Choose documents" });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Use 0 documents" })).toBeDisabled();
      await expect(dialog.getByRole("heading", { name: "Choose documents" })).toBeInViewport();
      await expect(dialog.getByRole("checkbox", { name: first.original_filename })).toBeVisible();
      expect((await new AxeBuilder({ page }).include("dialog[open]").analyze()).violations).toEqual([]);
      expect(await dialog.locator(".modal-box").evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath("choose-documents.png") });
      await dialog.getByRole("checkbox", { name: first.original_filename }).check();
      await page.keyboard.press("Escape");
      await expect(dialog).not.toBeVisible();
      await expect(trigger).toBeFocused();
      expect(submitted).toBeUndefined();
      await expect(page.getByLabel("Document limit")).toHaveValue("5");
      await trigger.click();
      await expect(dialog.getByRole("checkbox", { name: first.original_filename })).not.toBeChecked();
      await dialog.getByRole("button", { name: "Select this page" }).click();
      await expect(dialog.getByText("25 selected", { exact: true })).toBeVisible();
      await dialog.getByRole("button", { name: "Deselect this page" }).click();
      await dialog.getByRole("checkbox", { name: first.original_filename }).check();
      await dialog.getByRole("button", { name: "Next", exact: true }).click();
      await dialog.getByRole("checkbox", { name: second.original_filename }).check();
      await dialog.getByLabel("Search", { exact: true }).fill("Quarterly");
      await expect.poll(() => listRequests.at(-1)?.searchParams.get("search")).toBe("Quarterly");
      await expect(dialog.getByRole("checkbox", { name: second.original_filename })).toBeChecked();
      await dialog.getByRole("button", { name: "Use 2 documents" }).click();
      await expect(dialog).not.toBeVisible();
      const change = scope.getByRole("button", { name: "Change selection" });
      await expect(change).toBeFocused();
      expect(submitted).toBeUndefined();
      await expect(scope.getByText("2 documents selected")).toBeVisible();
      await expect(scope.getByLabel("Document limit")).toHaveCount(0);
      await expect(scope.getByRole("button", { name: "Use all eligible documents" })).toBeVisible();
      await page.screenshot({ path: testInfo.outputPath("selected-run-documents.png") });
      if (viewport.width === 1440) {
        await page.setViewportSize({ width: 720, height: 450 });
        await change.click();
        await expect(dialog).toHaveAttribute("open", "");
        await expect(dialog.getByRole("heading", { name: "Choose documents" })).toBeFocused();
        await expect(dialog.getByRole("heading", { name: "Choose documents" })).toBeInViewport();
        await page.keyboard.press("Tab");
        await expect(dialog.getByLabel("Search", { exact: true })).toBeFocused();
        await change.evaluate((element) => element.focus());
        expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
        const box = await dialog.locator(".modal-box").boundingBox();
        expect(box!.y).toBeGreaterThanOrEqual(16);
        expect(box!.y + box!.height).toBeLessThanOrEqual(434);
        expect(await dialog.locator(".modal-box").evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
        await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
        await expect(change).toBeFocused();
        await page.setViewportSize(viewport);
      }
      await change.click();
      await dialog.getByRole("button", { name: "Clear selection" }).click();
      await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
      await expect(dialog).not.toBeVisible();
      await expect(page.getByText("2 documents selected")).toBeVisible();
      await page.getByRole("button", { name: "Start run", exact: true }).click();
      await expect(page).toHaveURL(/\/runs\/run-1$/);
      expect(submitted?.document_ids).toEqual([DOCUMENT.id, "doc-2"]);
      expect(submitted).not.toHaveProperty("sample_size");
      expect(
        listRequests.every(
          (url) => url.searchParams.get("dataset") === DATASET.id && url.searchParams.get("runnable") === "true",
        ),
      ).toBe(true);
    });
  }
}
