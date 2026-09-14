import AxeBuilder from "@axe-core/playwright";
import type { Page, Route } from "@playwright/test";
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
} from "./support/api";
import { expect, test } from "./support/test";

const START = "2026-09-13T12:00:00.000Z";
const NOW = "2026-09-13T12:00:30.000Z";

function processing(operation = "extracting", completed = 1) {
  return {
    phase: "analyzing",
    operation,
    phase_started_at: START,
    operation_started_at: START,
    completed_phases: ["reading_document"],
    counter: { completed, total: 4, unit: "chunks" },
    segment: { current: 1, total: 2 },
    retry_at: null,
  };
}

function item(index: number, status = "running") {
  return {
    id: `item-${index}`,
    run: RUN.id,
    document: `document-${index}`,
    document_name: index === 1 ? DOCUMENT.original_filename : `Statement ${index}.pdf`,
    status,
    stage: status === "running" ? "workflow" : status,
    attempts: status === "queued" ? 0 : 1,
    duration_ms: null,
    error_code: "",
    error_message: "",
    retryable: false,
    created: START,
    modified: NOW,
    input_quality: null,
    progress_updated_at: NOW,
    processing_progress: status === "running" ? processing() : null,
  };
}

async function mockRun(page: Page, reject: (route: Route) => Promise<void>, count = 5) {
  const state = {
    run: { ...RUN, started_at: START, created: START, total_items: count },
    items: Array.from({ length: count }, (_, index) => item(index + 1, index < 2 ? "running" : "queued")),
    asOf: NOW,
    progressUnavailable: false,
    progressRequests: 0,
    itemRequests: [] as URL[],
  };
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1", "");
    if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
    if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
    if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
    if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
    if (path === "/runs/") return fulfillApi(route, apiPage([state.run]));
    if (path === `/runs/${RUN.id}/`) return fulfillApi(route, state.run);
    if (path === `/runs/${RUN.id}/usage/`) return fulfillApi(route, { calls: 0, by_item: [] });
    if (path === "/fields/") return fulfillApi(route, apiPage([]));
    if (path === `/runs/${RUN.id}/progress/`) {
      state.progressRequests += 1;
      if (state.progressUnavailable) return fulfillApi(route, null, 503);
      const counts = Object.fromEntries(
        ["running", "queued", "succeeded", "failed", "skipped"].map((status) => [
          status,
          state.items.filter((entry) => entry.status === status).length,
        ]),
      );
      return fulfillApi(route, {
        ...counts,
        total: count,
        remaining: counts.running + counts.queued,
        stage: state.run.stage,
        as_of: state.asOf,
        last_milestone_at: NOW,
        estimated_seconds_remaining: null,
        estimated_finish_at: null,
        activity_items: state.items.filter((entry) => ["running", "queued"].includes(entry.status)).slice(0, 5),
      });
    }
    if (path === "/run-items/") {
      state.itemRequests.push(url);
      const statuses = (url.searchParams.get("status__in") || url.searchParams.get("status"))?.split(",");
      const search = url.searchParams.get("search")?.toLowerCase();
      const filtered = state.items.filter(
        (entry) =>
          (!statuses || statuses.includes(entry.status)) &&
          (!search || entry.document_name.toLowerCase().includes(search)),
      );
      const pageNumber = Number(url.searchParams.get("page") || 1);
      const pageSize = Number(url.searchParams.get("page_size") || 50);
      return fulfillApi(route, {
        count: filtered.length,
        page: pageNumber,
        page_size: pageSize,
        total_pages: Math.ceil(filtered.length / pageSize),
        results: filtered.slice((pageNumber - 1) * pageSize, pageNumber * pageSize),
      });
    }
    return reject(route);
  });
  return state;
}

const viewports = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
];

for (const theme of ["light", "dark"] as const) {
  for (const viewport of viewports) {
    test(`active processing is readable and accessible · ${theme} · ${viewport.width}`, async ({
      page,
      apiGuard,
    }, testInfo) => {
      await page.setViewportSize(viewport);
      await page.emulateMedia({ reducedMotion: "reduce" });
      await prepareWorkspace(page, E2E_USER.username, theme);
      await mockRun(page, apiGuard.reject);
      await page.goto(`/runs/${RUN.id}`);
      await expect(page.getByText("Extracting fields", { exact: true }).first()).toBeVisible();
      const details = page.locator("summary").filter({ hasText: "Processing details" }).first();
      await details.focus();
      await page.keyboard.press("Enter");
      await expect(details.locator("..")).toHaveAttribute("open", "");
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
      await page.screenshot({ path: testInfo.outputPath("active-progress.png"), fullPage: true });
    });
  }
}

test("updates actual operations without closing details or moving keyboard focus, then finishes", async ({
  page,
  apiGuard,
}) => {
  await prepareWorkspace(page);
  await page.clock.install({ time: new Date(NOW) });
  const state = await mockRun(page, apiGuard.reject);
  await page.goto(`/runs/${RUN.id}`);
  const details = page.locator("summary").filter({ hasText: "Processing details" }).first();
  await details.focus();
  await page.keyboard.press("Enter");
  state.items[0].processing_progress = processing("checking_evidence", 2);
  state.asOf = "2026-09-13T12:00:33.000Z";
  await page.clock.runFor(3_100);
  await expect(page.getByText("Checking evidence", { exact: true }).first()).toBeVisible();
  await expect(details).toBeFocused();
  await expect(details.locator("..")).toHaveAttribute("open", "");
  state.items = state.items.map((entry) => ({ ...entry, status: "succeeded", processing_progress: null }));
  state.run = { ...state.run, status: "succeeded", stage: "finalized", processed_items: 5 };
  await page.clock.runFor(3_100);
  await expect(page.getByRole("button", { name: "Cancel run", exact: true })).not.toBeVisible();
  await expect(page.locator("#run-items").getByText("Succeeded", { exact: true })).toHaveCount(5);
  const finalRequests = state.progressRequests;
  await page.clock.runFor(10_000);
  expect(state.progressRequests).toBe(finalRequests);
});

test("keeps the last snapshot through interrupted updates and recovers on refresh", async ({ page, apiGuard }) => {
  await prepareWorkspace(page);
  await page.clock.install({ time: new Date(NOW) });
  const state = await mockRun(page, apiGuard.reject);
  await page.goto(`/runs/${RUN.id}`);
  await expect(page.getByText("Extracting fields", { exact: true }).first()).toBeVisible();
  state.progressUnavailable = true;
  await page.clock.runFor(16_000);
  await expect(page.getByText("Updates interrupted", { exact: true })).toBeVisible();
  await expect(page.getByText("Extracting fields", { exact: true }).first()).toBeVisible();
  state.progressUnavailable = false;
  state.asOf = "2026-09-13T12:00:46.000Z";
  await page.getByRole("button", { name: /Retry refresh/i }).click();
  await expect(page.getByText("Updates interrupted", { exact: true })).not.toBeVisible();
});

test("filters global activity counts and resets pagination without changing run totals", async ({ page, apiGuard }) => {
  await prepareWorkspace(page);
  const state = await mockRun(page, apiGuard.reject, 55);
  await page.goto(`/runs/${RUN.id}`);
  await expect(page.locator("#run-items").getByRole("row")).toHaveCount(51);
  await page.locator("#run-items").getByRole("button", { name: "Next page" }).click();
  await expect(page.locator("#run-items").getByRole("row")).toHaveCount(6);
  await page.getByRole("button", { name: /Processing.*2|2.*Processing/i }).click();
  await expect(page.locator("#run-items").getByRole("row")).toHaveCount(3);
  expect(state.itemRequests.at(-1)?.searchParams.get("page")).toBe("1");
  expect(state.itemRequests.at(-1)?.searchParams.get("status")).toBe("running");
  await expect(page.getByRole("button", { name: /Queued.*53|53.*Queued/i })).toBeVisible();
});
