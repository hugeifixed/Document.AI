import AxeBuilder from "@axe-core/playwright";
import { apiPage, DASHBOARD, DATASET, E2E_USER, fulfillApi, prepareWorkspace, PROJECT, RUN } from "./support/api";
import { expect, test } from "./support/test";

test.use({ viewport: { width: 800, height: 600 } });

test("keeps every export format visible outside the table scroll region", async ({ page, apiGuard }) => {
  const completedRun = {
    ...RUN,
    status: "succeeded",
    stage: "completed",
    processed_items: 1,
    finished_at: "2026-09-11T12:01:00Z",
  };
  await prepareWorkspace(page);
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
    if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
    if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
    if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
    if (path === "/runs/") return fulfillApi(route, apiPage([completedRun]));
    return apiGuard.reject(route);
  });

  await page.goto(`/exports?run=${RUN.id}`);
  const trigger = page.getByRole("button", { name: `Download ${completedRun.name}` });
  await trigger.click();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");

  const links = page.getByRole("link").filter({ hasText: /JSON package|CSV fields|Excel workbook/ });
  await expect(links).toHaveCount(3);
  for (const link of await links.all()) {
    await expect(link).toBeVisible();
    expect(
      await link.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        const target = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
        return target === element || element.contains(target);
      }),
      "The center of each menu item should be painted and clickable",
    ).toBe(true);
  }
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.keyboard.press("Escape");
  await expect(links.first()).toBeHidden();
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
});
