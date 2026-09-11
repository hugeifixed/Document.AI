import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { Buffer } from "node:buffer";
import {
  apiPage,
  DASHBOARD,
  DATASET,
  DOCUMENT,
  E2E_USER,
  fulfillApi,
  fulfillNotFound,
  prepareWorkspace,
  PROJECT,
  RUN,
  WORKFLOW,
} from "./support/api";

test.use({ viewport: { width: 768, height: 1024 } });

test("uploads a document, starts a run, and requests cancellation", async ({ page }) => {
  let createdRun = false;
  await prepareWorkspace(page);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
    if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
    if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
    if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
    if (path === "/documents/") return fulfillApi(route, apiPage([DOCUMENT]));
    if (path === `/datasets/${DATASET.id}/upload/` && request.method() === "POST") {
      return fulfillApi(route, { accepted: [DOCUMENT], rejected: [] }, 201);
    }
    if (path === "/workflows/") return fulfillApi(route, apiPage([WORKFLOW]));
    if (path === "/runs/" && request.method() === "GET") {
      return fulfillApi(route, apiPage(createdRun ? [RUN] : []));
    }
    if (path === "/runs/" && request.method() === "POST") {
      createdRun = true;
      return fulfillApi(route, RUN, 202);
    }
    if (path === `/runs/${RUN.id}/` && request.method() === "GET") return fulfillApi(route, RUN);
    if (path === `/runs/${RUN.id}/progress/`) {
      return fulfillApi(route, {
        total: 1,
        succeeded: 0,
        failed: 0,
        skipped: 0,
        queued: 0,
        running: 1,
        remaining: 1,
        stage: "processing",
        estimated_seconds_remaining: null,
      });
    }
    if (path === "/run-items/") return fulfillApi(route, apiPage([]));
    if (path === `/runs/${RUN.id}/cancel/` && request.method() === "POST") {
      return fulfillApi(route, { ...RUN, cancel_requested: true, stage: "cancelling" }, 202);
    }
    return fulfillNotFound(route);
  });

  await page.goto("/datasets");
  await expect(page.getByRole("heading", { name: "Datasets & documents" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "extract-dark");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Switch to light theme" }).click();

  await page.getByLabel("Choose documents").setInputFiles({
    name: "new-statement.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("statement"),
  });
  await page.getByRole("button", { name: "Upload 1 file" }).click();
  await expect(page.getByText(/Accepted$/)).toBeVisible();

  await page.goto("/runs");
  await page.getByLabel("Workflow").selectOption(WORKFLOW.id);
  await page.getByLabel("Name").fill("Browser run");
  await page.getByRole("button", { name: "Start run" }).click();
  await expect(page).toHaveURL(new RegExp(`/runs/${RUN.id}$`));
  await page.getByRole("button", { name: "Cancel run" }).click();
  await expect(page.locator("output").getByText("Cancellation requested", { exact: true })).toBeVisible();
});
