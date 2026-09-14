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
} from "./support/api";
import { expect, test } from "./support/test";

const viewports = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
];

for (const theme of ["light", "dark"] as const) {
  for (const viewport of viewports) {
    test(`scan details distinguish preparation from later failures · ${theme} · ${viewport.width}`, async ({
      page,
      apiGuard,
    }, testInfo) => {
      await page.setViewportSize(viewport);
      await prepareWorkspace(page, E2E_USER.username, theme);
      const quality = {
        mode: "adaptive",
        status: "applied",
        profile: "adaptive-v1",
        pages_examined: 2,
        pages_adjusted: 1,
        pages_skipped: 0,
        duration_ms: 1875,
        warnings: [],
      };
      const items = [
        {
          id: "item-w2",
          run: RUN.id,
          document: DOCUMENT.id,
          document_name: "W2_Multi_Sample_Data_input_IRS2_noisy_10492.pdf",
          status: "failed",
          stage: "workflow",
          attempts: 9,
          duration_ms: 1880,
          error_code: "AZURE_404",
          error_message:
            "Azure could not find the resource or model deployment. Check the endpoint, deployment name, and API version before retrying.",
          retryable: false,
          input_quality: quality,
        },
        {
          id: "item-agreement",
          run: RUN.id,
          document: "document-2",
          document_name: "4458862 Chromebook Agreement.pdf",
          status: "failed",
          stage: "layout",
          attempts: 6,
          duration_ms: 117,
          error_code: "INCOMPLETE_LAYOUT",
          error_message: "Layout analysis covered 2 of 3 expected pages. Check the service page limit before retrying.",
          retryable: false,
          input_quality: { ...quality, status: "bypassed", pages_examined: 3, pages_adjusted: 0 },
        },
        {
          id: "item-timeout",
          run: RUN.id,
          document: "document-3",
          document_name: "Statement.pdf",
          status: "failed",
          stage: "layout",
          attempts: 4,
          duration_ms: 30175,
          error_code: "AZURE_TIMEOUT",
          error_message: "Azure did not respond in time. Please try again.",
          retryable: true,
        },
      ];
      const run = { ...RUN, status: "failed", stage: "finalized", total_items: 3, processed_items: 3, failed_items: 3 };
      await page.route("**/api/v1/**", async (route) => {
        const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
        if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
        if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
        if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
        if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
        if (path === "/runs/") return fulfillApi(route, apiPage([run]));
        if (path === `/runs/${RUN.id}/`) return fulfillApi(route, run);
        if (path === `/runs/${run.id}/progress/`) return fulfillApi(route, runProgress(run));
        if (path === `/runs/${RUN.id}/usage/`) return fulfillApi(route, { calls: 0, by_item: [] });
        if (path === "/run-items/") return fulfillApi(route, apiPage(items));
        if (path === "/fields/") return fulfillApi(route, apiPage([]));
        return apiGuard.reject(route);
      });
      await page.goto(`/runs/${RUN.id}`);
      const trigger = page.getByRole("button", { name: `Scan details for ${items[0].document_name}` });
      await expect(trigger).toBeVisible();
      const fileLink = page.getByRole("link", { name: items[0].document_name, exact: true });
      await expect(fileLink).toHaveAttribute("title", items[0].document_name);
      expect(await fileLink.evaluate((element) => element.getBoundingClientRect().width)).toBeLessThanOrEqual(256);
      const alignment = await trigger.evaluate((element) => {
        const cells = element.closest("tr")!.querySelectorAll("th[scope='row'], td");
        const rects = [
          cells[0].querySelector("a")!,
          cells[1].querySelector(".badge")!,
          cells[2].firstElementChild!,
          cells[3].firstElementChild!,
          cells[4].firstElementChild!,
          cells[5].querySelector("p")!,
        ].map((entry) => entry.getBoundingClientRect());
        const centers = rects.map((rect) => rect.y + rect.height / 2);
        const textStart = element.querySelector("span")!.getBoundingClientRect().x;
        return {
          verticalSpread: Math.max(...centers) - Math.min(...centers),
          actionIndent: Math.abs(textStart - rects[1].x),
        };
      });
      expect(alignment.verticalSpread).toBeLessThanOrEqual(2);
      expect(alignment.actionIndent).toBeLessThanOrEqual(2);
      const retry = page.getByText("Retry available", { exact: true });
      expect(
        await retry.evaluate(
          (element) =>
            element.getBoundingClientRect().top - element.previousElementSibling!.getBoundingClientRect().bottom,
        ),
      ).toBeGreaterThanOrEqual(8);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.locator("#run-items").screenshot({ path: testInfo.outputPath("run-items.png") });
      const rowHeight = await trigger.evaluate((element) => element.closest("tr")!.getBoundingClientRect().height);
      await trigger.focus();
      await page.keyboard.press("Enter");
      const dialog = page.getByRole("dialog", { name: "Scan details" });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByText("Layout analysis finished, but the extraction workflow failed.")).toBeVisible();
      await expect(dialog.getByText(items[0].error_message)).toBeVisible();
      expect(await trigger.evaluate((element) => element.closest("tr")!.getBoundingClientRect().height)).toBe(
        rowHeight,
      );
      await page.keyboard.press("Tab");
      expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
      expect((await new AxeBuilder({ page }).include("dialog[open]").analyze()).violations).toEqual([]);
      await page.screenshot({ path: testInfo.outputPath("scan-details.png") });
      await page.keyboard.press("Escape");
      await expect(trigger).toBeFocused();
      await expect(dialog).not.toBeVisible();
      await page.getByRole("button", { name: `Scan details for ${items[1].document_name}` }).click();
      await expect(dialog.getByText("Layout analysis could not be completed.")).toBeVisible();
      await dialog.getByRole("button", { name: "Close", exact: true }).click();
      await expect(dialog).not.toBeVisible();
      // 200% desktop zoom gives a 1440x900 window a 720x450 CSS viewport.
      await page.setViewportSize({ width: 720, height: 450 });
      await trigger.click();
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole("heading", { name: "Scan details", exact: true })).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(await dialog.locator(".modal-box").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
        true,
      );
      const box = await dialog.locator(".modal-box").boundingBox();
      expect(box!.y).toBeGreaterThanOrEqual(16);
      expect(box!.y + box!.height).toBeLessThanOrEqual(434);
      await dialog.getByRole("button", { name: "Close", exact: true }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath("scan-details-zoom.png") });
      await dialog.getByRole("button", { name: "Close", exact: true }).click();
      await expect(trigger).toBeFocused();
    });
  }
}
