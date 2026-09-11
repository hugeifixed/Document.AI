import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import {
  apiPage,
  DASHBOARD,
  DATASET,
  E2E_USER,
  fulfillApi,
  fulfillNotFound,
  prepareWorkspace,
  PROJECT,
} from "./support/api";

test("signs in, opens the native account popover, and logs out", async ({ page }) => {
  let signedIn = false;
  await prepareWorkspace(page);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    if (path === "/auth/session/") return fulfillApi(route, { user: signedIn ? E2E_USER : null });
    if (path === "/auth/login/" && request.method() === "POST") {
      signedIn = true;
      return fulfillApi(route, { user: E2E_USER });
    }
    if (path === "/auth/logout/" && request.method() === "POST") {
      signedIn = false;
      return fulfillApi(route, null);
    }
    if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
    if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
    if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
    return fulfillNotFound(route);
  });

  await page.goto("/login?next=/");
  await expect(page.getByRole("heading", { name: "Sign in to DocAI" })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.getByLabel("Username").fill(E2E_USER.username);
  await page.getByLabel("Password").fill("correct-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: `Welcome back, ${E2E_USER.username}` })).toBeVisible();

  const trigger = page.getByRole("button", { name: `Account menu for ${E2E_USER.username}` });
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await trigger.click();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("link", { name: "Settings" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(trigger).toHaveAttribute("aria-expanded", "false");

  await trigger.click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to DocAI" })).toBeVisible();
});
