import AxeBuilder from "@axe-core/playwright";
import type { Page, Route } from "@playwright/test";
import { apiPage, DASHBOARD, DATASET, E2E_USER, fulfillApi, prepareWorkspace, PROJECT } from "./support/api";
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
    if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
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
        await expect(page.getByRole("main").getByRole("heading", { name, exact: true })).toBeVisible();
      }
      const inspectionControls = page.getByRole("combobox", { name: /^Inspect / });
      await expect(inspectionControls).toHaveCount(7);
      for (const control of await inspectionControls.all()) {
        await control.focus();
        // Outlines paint outside the control; visibility of the select itself
        // does not establish that a chart's clipping containers preserve its ring.
        const focusRing = await control.evaluate((element) => {
          const box = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          const ring = parseFloat(style.outlineWidth) + parseFloat(style.outlineOffset);
          const clipped: string[] = [];
          for (let parent = element.parentElement; parent; parent = parent.parentElement) {
            const overflow = getComputedStyle(parent);
            const rect = parent.getBoundingClientRect();
            const top = rect.top + parent.clientTop;
            const left = rect.left + parent.clientLeft;
            if (/(hidden|clip|auto|scroll)/.test(overflow.overflowY)) {
              if (box.top - ring < top - 0.5) clipped.push("top");
              if (box.bottom + ring > top + parent.clientHeight + 0.5) clipped.push("bottom");
            }
            if (/(hidden|clip|auto|scroll)/.test(overflow.overflowX)) {
              if (box.left - ring < left - 0.5) clipped.push("left");
              if (box.right + ring > left + parent.clientWidth + 0.5) clipped.push("right");
            }
          }
          return { ring, clipped };
        });
        expect(focusRing.ring).toBeGreaterThan(0);
        expect(focusRing.clipped, (await control.getAttribute("aria-label")) ?? "Chart inspection").toEqual([]);
      }
      const inspect = page.getByRole("combobox", { name: /^Inspect / }).first();
      await inspect.focus();
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("Enter");
      await expect.soft(page.getByRole("tooltip")).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(page.getByRole("tooltip")).not.toBeVisible();
      await expect(inspect).toBeFocused();
      await inspect.locator("xpath=ancestor::section[1]").screenshot({ path: info.outputPath("focused-chart.png") });
      const disclosure = page.locator("summary").filter({ hasText: "Show data table" }).first();
      const adjacentPlot = page.locator("svg[aria-labelledby]").nth(1);
      const adjacentTop = (await adjacentPlot.boundingBox())!.y;
      await disclosure.focus();
      await expect(disclosure).toBeFocused();
      await page.keyboard.press("Enter");
      const table = disclosure.locator("..").getByRole("table");
      await expect(table).toBeVisible();
      if (viewport.width === 1440) {
        expect(Math.abs((await adjacentPlot.boundingBox())!.y - adjacentTop)).toBeLessThan(1);
      }
      const numeric = table.locator("tbody td").first();
      await expect(numeric).toHaveCSS("text-align", "right");
      expect((await table.locator("tbody tr").first().boundingBox())!.height).toBeGreaterThanOrEqual(48);
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
  await page.getByRole("combobox", { name: "Job status", exact: true }).selectOption("failed");
  await expect(page).toHaveURL(/status=failed/);
  await page.getByRole("combobox", { name: "Provider", exact: true }).selectOption("azure_openai");
  await expect(page).toHaveURL(/provider=azure_openai/);
  await expect.poll(() => requests.some((url) => url.searchParams.get("provider") === "azure_openai")).toBe(true);
  const processingRequests = requests.filter((url) => url.pathname === "/api/v1/metrics/");
  const usageRequests = requests.filter((url) => url.pathname === "/api/v1/metrics/usage/");
  expect(processingRequests.every((url) => !url.searchParams.has("provider"))).toBe(true);
  expect(usageRequests.every((url) => !url.searchParams.has("status"))).toBe(true);
  expect(requests.every((url) => url.searchParams.get("dataset") === DATASET.id)).toBe(true);
  await page.goBack();
  await expect(page.getByRole("combobox", { name: "Provider", exact: true })).toHaveValue("");
  await expect(page.getByRole("combobox", { name: "Job status", exact: true })).toHaveValue("failed");
  await page.goBack();
  await expect(page.getByRole("combobox", { name: "Job status", exact: true })).toHaveValue("");
  await page.goForward();
  await expect(page.getByRole("combobox", { name: "Job status", exact: true })).toHaveValue("failed");
});

test("reviewers see operations without requesting restricted LLM usage", async ({ page, apiGuard }) => {
  await prepareWorkspace(page);
  await mockMetrics(page, apiGuard.reject, false);
  await page.goto("/metrics");
  await expect(page.getByRole("main").getByRole("heading", { name: "Review", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "LLM usage", exact: true })).not.toBeVisible();
  await expect(page.getByRole("combobox", { name: "Provider", exact: true })).not.toBeVisible();
});

for (const filter of [
  { name: "Document type", value: "w2", endpoint: "metrics" },
  { name: "Job status", value: "failed", endpoint: "metrics" },
  { name: "Provider", value: "azure_openai", endpoint: "metrics/usage" },
  { name: "Deployment", value: "extraction", endpoint: "metrics/usage" },
  { name: "Stage", value: "extraction", endpoint: "metrics/usage" },
]) {
  test(`uncached ${filter.name} keeps keyboard focus while results load`, async ({ page, apiGuard }) => {
    await prepareWorkspace(page);
    await mockMetrics(page, apiGuard.reject);
    await page.goto("/metrics");
    await expect(page.getByText("Recorded responses", { exact: true })).toBeVisible();
    let release!: () => void;
    const response = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route(`**/api/v1/${filter.endpoint}/?**`, async (route) => {
      await response;
      await fulfillApi(route, filter.endpoint === "metrics" ? metrics : usage);
    });
    const select = page.getByRole("combobox", { name: filter.name, exact: true });
    await select.focus();
    await select.selectOption(filter.value);
    await expect(
      page.getByRole("status", { name: filter.endpoint === "metrics" ? "Loading metrics" : "Loading LLM usage" }),
    ).toBeVisible();
    await expect(select).toBeFocused();
    await expect(select).toHaveValue(filter.value);
    await expect(
      page.getByText(filter.endpoint === "metrics" ? "Completed jobs" : "Recorded responses", { exact: true }),
    ).not.toBeVisible();
    release();
    await expect(
      page.getByText(filter.endpoint === "metrics" ? "Completed jobs" : "Recorded responses", { exact: true }),
    ).toBeVisible();
    await expect(select).toBeFocused();
  });
}

test("cached history reads current inspected numbers and retains measured zeroes", async ({ page, apiGuard }) => {
  await prepareWorkspace(page);
  await mockMetrics(page, apiGuard.reject);
  await page.route("**/api/v1/metrics/?**", async (route) => {
    const filtered = new URL(route.request().url()).searchParams.has("status");
    await fulfillApi(route, {
      ...metrics,
      processing: {
        ...metrics.processing,
        daily: metrics.processing.daily.map((day) => ({
          ...day,
          median_duration_ms: filtered ? 0 : 5000,
          p95_duration_ms: filtered ? 0 : 17000,
        })),
      },
    });
  });
  await page.goto("/metrics");
  const status = page.getByRole("combobox", { name: "Job status", exact: true });
  await status.selectOption("failed");
  const inspect = page.getByRole("combobox", { name: "Inspect Daily duration", exact: true });
  await inspect.focus();
  await inspect.selectOption(dates[0]);
  await expect(page.getByRole("tooltip")).toContainText("Median: 0 s");
  await page.goBack();
  await expect(status).toHaveValue("");
  await expect(page.getByRole("tooltip")).toContainText("Median: 5 s");
  await page.goForward();
  await expect(status).toHaveValue("failed");
  await expect(page.getByRole("tooltip")).toContainText("Median: 0 s");
});

test("invalid custom dates identify both affected inputs", async ({ page, apiGuard }) => {
  await prepareWorkspace(page);
  await mockMetrics(page, apiGuard.reject);
  await page.goto("/metrics?range=custom&start=2026-09-01&end=2026-09-03");
  await page.getByLabel(/End date/).fill("2026-08-01");
  await page.getByRole("button", { name: "Apply dates" }).click();
  const error = page.getByRole("alert");
  await expect(error).toBeVisible();
  for (const name of ["Start date", "End date"]) {
    const input = page.getByLabel(new RegExp(name));
    await expect(input).toHaveAttribute("aria-invalid", "true");
    await expect(input).toHaveAccessibleDescription((await error.textContent())!);
  }
});

test("single-date inspection can reopen after every dismissal", async ({ page, apiGuard }) => {
  await prepareWorkspace(page);
  await mockMetrics(page, apiGuard.reject);
  await page.route("**/api/v1/metrics/?**", (route) =>
    fulfillApi(route, {
      ...metrics,
      processing: { ...metrics.processing, daily: [metrics.processing.daily[0]] },
    }),
  );
  await page.goto("/metrics?range=today");
  const inspect = page.getByRole("combobox", { name: "Inspect Daily duration", exact: true });
  for (const dismiss of ["escape", "placeholder", "blur"]) {
    await inspect.focus();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("tooltip")).toContainText("Median: 5 s");
    if (dismiss === "escape") await page.keyboard.press("Escape");
    if (dismiss === "placeholder") await inspect.selectOption("");
    if (dismiss === "blur") await page.getByRole("combobox", { name: "Date range", exact: true }).focus();
    await expect(page.getByRole("tooltip")).not.toBeVisible();
    await expect(inspect).toHaveValue("");
  }
  await inspect.focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("tooltip")).toContainText("Median: 5 s");
});
