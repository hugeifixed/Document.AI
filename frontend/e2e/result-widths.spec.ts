import AxeBuilder from "@axe-core/playwright";
import {
  apiPage,
  DASHBOARD,
  DATASET,
  E2E_USER,
  FIELD,
  fulfillApi,
  prepareWorkspace,
  PROJECT,
  RUN,
} from "./support/api";
import { expect, test } from "./support/test";

for (const theme of ["light", "dark"] as const) {
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
    { width: 1440, height: 900 },
  ]) {
    test(`long result content stays compact · ${theme} · ${viewport.width}`, async ({ page, apiGuard }, testInfo) => {
      await page.setViewportSize(viewport);
      await prepareWorkspace(page, E2E_USER.username, theme);
      const field = {
        ...FIELD,
        name: "account_holder_".repeat(12),
        document_name: `${"annual_banking_document_".repeat(12)}.pdf`,
        raw_value: "A lengthy extracted statement that includes multiple lines.\n".repeat(20),
        normalized_value: "long_normalized_value_".repeat(30),
      };
      await page.route("**/api/v1/**", (route) => {
        const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
        if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
        if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
        if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
        if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
        if (path === "/runs/") return fulfillApi(route, apiPage([RUN]));
        if (path === `/runs/${RUN.id}/`) return fulfillApi(route, RUN);
        if (path === "/segments/") return fulfillApi(route, apiPage([]));
        if (path === "/fields/")
          return fulfillApi(
            route,
            apiPage([
              field,
              { ...field, id: "short", name: "Short field", raw_value: "Short value", normalized_value: "Short value" },
            ]),
          );
        return apiGuard.reject(route);
      });
      await page.goto(`/results?run=${RUN.id}`);
      const table = page.getByRole("table", { name: "Extracted fields" });
      const name = table.getByRole("link", { name: field.name, exact: true });
      await expect(name).toBeVisible();
      await expect(name).toHaveAttribute(
        "href",
        `/documents/${field.document}?run=${field.run}&from=results&field=${field.id}`,
      );
      await expect(name).toHaveAttribute("title", field.name);
      const row = name.locator("xpath=ancestor::tr");
      const shortRow = table.getByRole("link", { name: "Short field", exact: true }).locator("xpath=ancestor::tr");
      expect(Math.abs((await row.boundingBox())!.height - (await shortRow.boundingBox())!.height)).toBeLessThanOrEqual(
        1,
      );
      for (const value of [field.raw_value, field.normalized_value]) {
        const cell = row.getByTitle(value, { exact: true });
        await expect(cell).toHaveText(value);
        expect(await cell.evaluate((element) => element.getBoundingClientRect().width)).toBeLessThanOrEqual(160);
      }
      expect(await name.evaluate((element) => element.getBoundingClientRect().width)).toBeLessThanOrEqual(160);
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
      await name.focus();
      await expect(name).toBeFocused();
      await page.screenshot({ path: testInfo.outputPath("results.png"), fullPage: true });
    });
  }
}
