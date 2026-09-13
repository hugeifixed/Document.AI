import AxeBuilder from "@axe-core/playwright";
import { apiPage, DASHBOARD, DATASET, E2E_USER, fulfillApi, prepareWorkspace, PROJECT, WORKFLOW } from "./support/api";
import { expect, test } from "./support/test";

for (const theme of ["light", "dark"] as const) {
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
    { width: 1440, height: 900 },
  ]) {
    test(`long workflow names stay compact and open in full · ${theme} · ${viewport.width}`, async ({
      page,
      apiGuard,
    }, testInfo) => {
      await page.setViewportSize(viewport);
      await prepareWorkspace(page, E2E_USER.username, theme);
      const workflow = {
        ...WORKFLOW,
        name: "Form W-2 and 1099 annual banking document validation and extraction · Unbundle, classify and extract",
        status: "draft",
        workflow_type: "unbundle_classify_extract",
      };
      await page.route("**/api/v1/**", (route) => {
        const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
        if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
        if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
        if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
        if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
        if (path === `/workflows/${workflow.id}/`) return fulfillApi(route, workflow);
        if (path === "/workflows/")
          return fulfillApi(route, apiPage([workflow, { ...workflow, id: "short", name: "Short name" }]));
        return apiGuard.reject(route);
      });
      await page.goto(`/configurations?created=${workflow.id}`);
      const table = page.getByRole("table", { name: "Workflow versions" });
      const name = table.getByRole("button", { name: workflow.name, exact: true });
      await expect(name).toBeVisible();
      const longRow = await name.locator("xpath=ancestor::tr").boundingBox();
      const shortRow = await table
        .getByRole("button", { name: "Short name", exact: true })
        .locator("xpath=ancestor::tr")
        .boundingBox();
      // The final row has no bottom divider; allow its one-pixel border difference.
      expect(Math.abs(longRow!.height - shortRow!.height)).toBeLessThanOrEqual(1);
      expect(await name.evaluate((element) => element.getBoundingClientRect().width)).toBeLessThanOrEqual(256);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(
        await table.evaluate((element) => {
          const region = element.parentElement!;
          return region.scrollHeight <= region.clientHeight;
        }),
      ).toBe(true);
      if (viewport.width === 1440) {
        expect(
          await table.evaluate((element) => element.parentElement!.scrollWidth - element.parentElement!.clientWidth),
        ).toBeLessThanOrEqual(0);
      }
      expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
      await page.screenshot({ path: testInfo.outputPath("workflow-names.png"), fullPage: true });
      await name.focus();
      await page.keyboard.press("Enter");
      const dialog = page.getByRole("dialog", { name: "Workflow version detail" });
      await expect(dialog.getByRole("heading", { name: `${workflow.name} v1`, exact: true })).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(name).toBeFocused();
    });
  }
}
