import AxeBuilder from "@axe-core/playwright";
import { apiPage, DASHBOARD, DATASET, E2E_USER, fulfillApi, prepareWorkspace, PROJECT, RUN } from "./support/api";
import { expect, test } from "./support/test";

const viewports = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
];

for (const theme of ["light", "dark"] as const) {
  for (const viewport of viewports) {
    test(`token usage starts compact and opens with the keyboard · ${theme} · ${viewport.width}`, async ({
      page,
      apiGuard,
    }, testInfo) => {
      await page.setViewportSize(viewport);
      await prepareWorkspace(page, E2E_USER.username, theme);
      const run = { ...RUN, status: "succeeded", stage: "finalized", processed_items: 1 };
      const tokens = { input_tokens: 123_455_789, output_tokens: 1_000, total_tokens: 123_456_789 };
      const usage = {
        run: run.id,
        calls: 2,
        measured_calls: 2,
        ...tokens,
        cached_input_tokens: 200,
        reasoning_tokens: 100,
        finish_reasons: { stop: 2 },
        safety_outcomes: { clear: 2 },
        by_stage: [{ stage: "extraction", calls: 2, measured_calls: 2, ...tokens }],
        by_item: [],
      };
      let usageRequests = 0;
      await page.route("**/api/v1/**", async (route) => {
        const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
        if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
        if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
        if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
        if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
        if (path === "/runs/") return fulfillApi(route, apiPage([run]));
        if (path === `/runs/${run.id}/`) return fulfillApi(route, run);
        if (path === `/runs/${run.id}/usage/`) {
          usageRequests += 1;
          return fulfillApi(route, usage);
        }
        if (path === "/run-items/" || path === "/fields/") return fulfillApi(route, apiPage([]));
        return apiGuard.reject(route);
      });

      await page.goto(`/runs/${run.id}`);
      const card = page.locator("details").filter({ has: page.getByText("LLM token usage", { exact: true }) });
      const summary = card.locator("summary");
      const breakdown = card.getByRole("table", { name: "LLM token usage by workflow stage" });
      const primaryColor = await card.evaluate((element) => {
        const probe = document.createElement("span");
        probe.style.color = "var(--color-primary)";
        element.append(probe);
        const color = getComputedStyle(probe).color;
        probe.remove();
        return color;
      });
      async function expectDisclosureFocus() {
        await expect(summary).toBeFocused();
        await expect(card).toHaveCSS("outline-style", "solid");
        await expect(card).toHaveCSS("outline-width", "2px");
        await expect(card).toHaveCSS("outline-offset", "2px");
        await expect(card).toHaveCSS("outline-color", primaryColor);
        await expect(summary).toHaveCSS("outline-style", "none");
      }

      await expect(summary).toContainText("123,456,789 tokens");
      await expect(card).not.toHaveAttribute("open");
      await expect(breakdown).not.toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await card.screenshot({ path: testInfo.outputPath("token-usage-collapsed.png") });

      await summary.focus();
      await page.keyboard.press("Shift+Tab");
      await page.keyboard.press("Tab");
      await expectDisclosureFocus();
      await page.screenshot({ path: testInfo.outputPath("token-usage-focused-closed.png") });
      await page.keyboard.press("Enter");
      await expect(summary).toBeFocused();
      await expect(card).toHaveAttribute("open");
      await expect(breakdown).toBeVisible();
      await expectDisclosureFocus();
      expect((await new AxeBuilder({ page }).include("details").analyze()).violations).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await card.screenshot({ path: testInfo.outputPath("token-usage-expanded.png") });
      if (viewport.width === 390) {
        const scrollRegion = card.getByRole("region", { name: "LLM token usage breakdown" });
        await page.keyboard.press("Tab");
        await expect(scrollRegion).toBeFocused();
        await page.keyboard.press("ArrowRight");
        await expect.poll(() => scrollRegion.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
        await page.keyboard.press("Shift+Tab");
        await expectDisclosureFocus();
      }

      await page.keyboard.press("Space");
      await expect(card).not.toHaveAttribute("open");
      await expect(breakdown).not.toBeVisible();
      await expectDisclosureFocus();
      // Expanding is a local disclosure, not a new request or a separate permission boundary.
      expect(usageRequests).toBe(1);
    });
  }
}
