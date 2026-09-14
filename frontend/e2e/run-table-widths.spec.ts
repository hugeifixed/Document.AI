import AxeBuilder from "@axe-core/playwright";
import {
  apiPage,
  DASHBOARD,
  DATASET,
  E2E_USER,
  fulfillApi,
  prepareWorkspace,
  PROJECT,
  RUN,
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
    test(`run search table stays compact · ${theme} · ${viewport.width}`, async ({ page, apiGuard }, testInfo) => {
      await page.setViewportSize(viewport);
      await prepareWorkspace(page, E2E_USER.username, theme);
      const run = {
        ...RUN,
        name: "Form W-2 · Unbundling + classification + extraction v1 · llm-normal · Sep 13, 2026, 17:18",
        workflow_name: "Extraction only: structured (layout-preserved, generic extractor)",
      };
      await page.route("**/api/v1/**", (route) => {
        const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
        if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
        if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
        if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
        if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
        if (path === "/workflows/") return fulfillApi(route, apiPage([WORKFLOW]));
        if (path === "/runs/")
          return fulfillApi(
            route,
            apiPage([run, { ...run, id: "short", name: "Short run", workflow_name: "Extract" }]),
          );
        return apiGuard.reject(route);
      });
      await page.goto("/runs");
      const table = page.getByRole("table", { name: "Runs", exact: true });
      const name = table.getByRole("button", { name: run.name, exact: true });
      await expect(name).toBeVisible();
      const longRow = await name.locator("xpath=ancestor::tr").boundingBox();
      const shortRow = await table
        .getByRole("button", { name: "Short run", exact: true })
        .locator("xpath=ancestor::tr")
        .boundingBox();
      expect(Math.abs(longRow!.height - shortRow!.height)).toBeLessThanOrEqual(1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(
        await table.evaluate((element) => element.parentElement!.scrollHeight <= element.parentElement!.clientHeight),
      ).toBe(true);
      if (viewport.width === 1440) {
        expect(
          await table.evaluate((element) => element.parentElement!.scrollWidth - element.parentElement!.clientWidth),
        ).toBeLessThanOrEqual(0);
      }
      expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
      await expect(table.getByTitle(run.name)).toHaveText(run.name);
      await expect(table.getByTitle(run.workflow_name)).toHaveText(run.workflow_name);
      await name.focus();
      await expect(name).toBeFocused();
      await page.getByRole("searchbox", { name: "Search", exact: true }).fill("W-2");
      await expect(page).toHaveURL(/q=W-2/);
      expect(await table.evaluate((el) => el.parentElement!.scrollHeight <= el.parentElement!.clientHeight)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath("runs-table.png"), fullPage: true });
    });
  }
}
