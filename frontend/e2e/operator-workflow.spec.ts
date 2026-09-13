import AxeBuilder from "@axe-core/playwright";
import { Buffer } from "node:buffer";
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
  WORKFLOW,
} from "./support/api";
import { expect, test } from "./support/test";

test.use({ viewport: { width: 768, height: 1024 } });

test("uploads a document, starts a run, and requests cancellation", async ({ page, apiGuard }) => {
  let createdRun = false;
  await prepareWorkspace(page);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
    if (path === "/dashboard/") {
      return fulfillApi(route, { ...DASHBOARD, review_queue: { fields: 4, classifications: 0 } });
    }
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
    if (path === `/runs/${RUN.id}/usage/`) {
      return fulfillApi(route, {
        run: RUN.id,
        calls: 0,
        measured_calls: 0,
        input_tokens: 0,
        cached_input_tokens: 0,
        output_tokens: 0,
        reasoning_tokens: 0,
        total_tokens: 0,
        finish_reasons: {},
        safety_outcomes: {},
        by_stage: [],
        by_item: [],
      });
    }
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
    return apiGuard.reject(route);
  });

  await page.goto("/datasets");
  await expect(page.getByRole("heading", { name: DATASET.name })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "extract-dark");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Switch to light theme" }).click();

  await page.getByText("Add documents", { exact: true }).click();
  await page.getByLabel("Choose documents").setInputFiles({
    name: "new-statement.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("statement"),
  });
  await page.getByRole("button", { name: "Upload 1 file" }).click();
  await expect(page.getByText(/Accepted$/)).toBeVisible();

  await page.getByRole("link", { name: /Start a run$/ }).click();
  await expect(page).toHaveURL(/\/runs\?dataset=dataset-1&workflow=workflow-1$/);
  const datasetSelect = page.getByLabel(/^Dataset \*$/);
  await expect(datasetSelect).toHaveValue(DATASET.id);
  await expect(datasetSelect).toHaveCSS("background-image", "none");
  const datasetCaret = datasetSelect.locator("xpath=../span[@aria-hidden='true']");
  await expect(datasetCaret).toBeVisible();
  const [selectBox, caretBox] = await Promise.all([datasetSelect.boundingBox(), datasetCaret.boundingBox()]);
  expect(selectBox).not.toBeNull();
  expect(caretBox).not.toBeNull();
  expect(caretBox!.x).toBeGreaterThan(selectBox!.x + selectBox!.width - 42);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.getByLabel("Workflow")).toHaveValue(WORKFLOW.id);
  await page.getByLabel("Name").fill("Browser run");
  await page.getByRole("button", { name: "Start run" }).click();
  await expect(page).toHaveURL(new RegExp(`/runs/${RUN.id}$`));
  await page.getByRole("button", { name: "Cancel run" }).click();
  await expect(page.locator("output").getByText("Cancellation requested", { exact: true })).toBeVisible();
});
