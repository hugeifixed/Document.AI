import AxeBuilder from "@axe-core/playwright";
import type { Page, Route } from "@playwright/test";
import { apiPage, DATASET, E2E_USER, fulfillApi, prepareWorkspace, PROJECT } from "./support/api";
import { expect, test } from "./support/test";

const dates = ["2026-09-01", "2026-09-02", "2026-09-03"];
const meta = {
  start_date: dates[0],
  end_date: dates[2],
  timezone: "UTC",
  as_of: "2026-09-03T12:00:00Z",
  cache_ttl_seconds: 60,
  applied_filters: {},
};
const metrics = {
  meta,
  processing: {
    completed_jobs: 12,
    duration_sample_count: 10,
    median_duration_ms: 5000,
    p95_duration_ms: 17000,
    daily: dates.map((date) => ({
      date,
      completed_jobs: 4,
      succeeded: 3,
      failed: 1,
      duration_sample_count: 3,
      median_duration_ms: 5000,
      p95_duration_ms: 17000,
    })),
    by_document_type: [
      { key: "w2", label: "W-2", executions: 10 },
      { key: "__unclassified__", label: "Not classified", executions: 2 },
    ],
    document_type_options: [
      { key: "w2", label: "W-2" },
      { key: "__unclassified__", label: "Not classified" },
    ],
    failures_by_phase: [
      { key: "workflow", label: "Workflow", count: 3 },
      { key: "layout", label: "Layout", count: 0 },
    ],
  },
  runs: {
    succeeded: 6,
    failed: 3,
    partial: 3,
    cancelled: 3,
    success_rate: 50,
    daily: dates.map((date) => ({ date, succeeded: 2, failed: 1, partial: 1, cancelled: 1 })),
  },
  review: {
    backlog_fields: 15,
    backlog_classifications: 2,
    backlog_documents: 4,
    decision_count: 9,
    field_decision_count: 6,
    field_correction_count: 2,
    field_correction_rate: 100 / 3,
    daily: dates.map((date) => ({ date, field_decisions: 2, classification_decisions: 1 })),
  },
};
const usage = {
  meta,
  calls: 6,
  measured_calls: 3,
  total_tokens: 12000,
  daily: dates.map((date) => ({ date, calls: 2, measured_calls: 1, total_tokens: 4000 })),
  filter_options: { providers: ["azure_openai"], deployments: ["extraction"], stages: ["extraction"] },
};

async function mockMetrics(page: Page, reject: (route: Route) => Promise<void>, operator = true) {
  const requests: URL[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1", "");
    if (path === "/auth/session/") {
      return fulfillApi(route, { user: operator ? E2E_USER : { ...E2E_USER, roles: ["docai_reviewers"] } });
    }
    if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
    if (path === `/projects/${PROJECT.id}/`) return fulfillApi(route, PROJECT);
    if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
    if (path === `/datasets/${DATASET.id}/`) return fulfillApi(route, DATASET);
    if (path === "/metrics/" || (operator && path === "/metrics/usage/")) {
      requests.push(url);
      return fulfillApi(route, path === "/metrics/" ? metrics : usage);
    }
    return reject(route);
  });
  return requests;
}

for (const theme of ["light", "dark"] as const) {
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
    { width: 1440, height: 900 },
  ]) {
    test(`metrics charts and tables are accessible · ${theme} · ${viewport.width}`, async ({
      page,
      apiGuard,
    }, info) => {
      await page.setViewportSize(viewport);
      await page.emulateMedia({ reducedMotion: "reduce" });
      await prepareWorkspace(page, E2E_USER.username, theme);
      await mockMetrics(page, apiGuard.reject);
      await page.goto("/metrics?range=custom&start=2026-09-01&end=2026-09-03");
      await expect(page).toHaveTitle(/Metrics \|/);
      for (const name of ["Metrics", "Processing", "Run reliability", "Review", "LLM usage"]) {
        await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
      }
      const inspect = page.getByRole("combobox", { name: /^Inspect / }).first();
      await inspect.focus();
      await page.keyboard.press("ArrowDown");
      await expect(page.getByRole("tooltip")).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("tooltip")).not.toBeVisible();
      await expect(inspect).toBeFocused();
      const disclosure = page.locator("summary").filter({ hasText: "Show data table" }).first();
      await disclosure.focus();
      await expect(disclosure).toBeFocused();
      await page.keyboard.press("Enter");
      const table = disclosure.locator("..").getByRole("table");
      await expect(table).toBeVisible();
      await expect(table.getByRole("rowheader", { name: "2026-09-01", exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
      await page.screenshot({ path: info.outputPath("metrics.png"), fullPage: true });
    });
  }
}

test("section filters remain separate and browser history restores them", async ({ page, apiGuard }) => {
  await prepareWorkspace(page);
  const requests = await mockMetrics(page, apiGuard.reject);
  await page.goto("/metrics");
  await page.getByLabel("Job status", { exact: true }).selectOption("failed");
  await expect(page).toHaveURL(/status=failed/);
  await page.getByLabel("Provider", { exact: true }).selectOption("azure_openai");
  await expect(page).toHaveURL(/provider=azure_openai/);
  await expect.poll(() => requests.some((url) => url.searchParams.get("provider") === "azure_openai")).toBe(true);
  const processingRequests = requests.filter((url) => url.pathname === "/api/v1/metrics/");
  const usageRequests = requests.filter((url) => url.pathname === "/api/v1/metrics/usage/");
  expect(processingRequests.every((url) => !url.searchParams.has("provider"))).toBe(true);
  expect(usageRequests.every((url) => !url.searchParams.has("status"))).toBe(true);
  expect(requests.every((url) => url.searchParams.get("dataset") === DATASET.id)).toBe(true);
  await page.goBack();
  await expect(page.getByLabel("Provider", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("Job status", { exact: true })).toHaveValue("failed");
  await page.goBack();
  await expect(page.getByLabel("Job status", { exact: true })).toHaveValue("");
  await page.goForward();
  await expect(page.getByLabel("Job status", { exact: true })).toHaveValue("failed");
});

test("reviewers see operations without requesting restricted LLM usage", async ({ page, apiGuard }) => {
  await prepareWorkspace(page);
  await mockMetrics(page, apiGuard.reject, false);
  await page.goto("/metrics");
  await expect(page.getByRole("heading", { name: "Review", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "LLM usage", exact: true })).not.toBeVisible();
  await expect(page.getByLabel("Provider", { exact: true })).not.toBeVisible();
});
