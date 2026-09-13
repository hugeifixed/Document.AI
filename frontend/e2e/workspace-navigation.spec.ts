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
  WORKFLOW,
} from "./support/api";
import { expect, test } from "./support/test";

const SECOND_PROJECT = { ...PROJECT, id: "project-2", name: "Retail operations", slug: "retail-operations" };
const SECOND_DATASET = { ...DATASET, id: "dataset-2", project: SECOND_PROJECT.id, name: "Payroll records" };
const SIBLING_DATASET = { ...DATASET, id: "dataset-3", name: "Quarterly records" };
const datasets = [DATASET, SECOND_DATASET, SIBLING_DATASET];
const document = { ...DOCUMENT, original_filename: "Workspace statement.txt" };
const run = { ...RUN, status: "succeeded", stage: "complete", processed_items: 1 };
const hint = "Changing workspace opens its documents.";
const dialogName = "Discard unsaved changes?";

/** Deliberately synthetic, read-only unless a test opts into one named form action. */
async function mockWorkspace(
  page: Page,
  reject: (route: Route) => Promise<void>,
  options: {
    documentGate?: Promise<void>;
    documentStatus?: number;
    labelSave?: "success" | "failure";
    validate?: boolean;
  } = {},
) {
  const requests: { method: string; url: URL; body: unknown }[] = [];
  const labels: Record<string, unknown>[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v1", "");
    requests.push({ method: request.method(), url, body: request.postData() ? request.postDataJSON() : null });
    if (request.method() === "POST" && path === "/labels/" && options.labelSave) {
      if (options.labelSave === "failure") return fulfillApi(route, null, 400);
      const label = {
        id: "label-1",
        document: document.id,
        field_name: "missing_value",
        expected_value: "",
        notes: "Checked source",
        is_absent: true,
        version: 1,
        mapping_method: "absent",
        mapping_exceptions: [],
        match_score: null,
        spans: [],
        status: "draft",
      };
      labels.push(label);
      return fulfillApi(route, label, 201);
    }
    if (request.method() === "POST" && path === "/workflows/validate/" && options.validate)
      return fulfillApi(route, { valid: true, content_hash: "sha256:1234567890abcdef" });
    if (request.method() !== "GET") return reject(route);
    if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
    if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
    if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT, SECOND_PROJECT]));
    const project = [PROJECT, SECOND_PROJECT].find((item) => path === `/projects/${item.id}/`);
    if (project) return fulfillApi(route, project);
    if (path === "/datasets/")
      return fulfillApi(
        route,
        apiPage(
          datasets.filter(
            (item) => !url.searchParams.get("project") || item.project === url.searchParams.get("project"),
          ),
        ),
      );
    const dataset = datasets.find((item) => path === `/datasets/${item.id}/`);
    if (dataset) return fulfillApi(route, dataset);
    if (path === `/documents/${document.id}/`) {
      await options.documentGate;
      return fulfillApi(route, options.documentStatus ? null : document, options.documentStatus ?? 200);
    }
    if (path === `/documents/${document.id}/units/0/`)
      return fulfillApi(route, { kind: "page", index: 0, content: "Account holder: Daniel Silva" });
    if (path === "/documents/") {
      const selected = datasets.find((item) => item.id === url.searchParams.get("dataset")) ?? DATASET;
      return fulfillApi(
        route,
        apiPage([{ ...document, id: `document-${selected.id}`, dataset: selected.id, dataset_name: selected.name }]),
      );
    }
    if (path === "/runs/")
      return fulfillApi(
        route,
        apiPage(
          url.searchParams.get("project") === SECOND_PROJECT.id ||
            url.searchParams.get("dataset") === SIBLING_DATASET.id
            ? []
            : [run],
        ),
      );
    if (path === `/runs/${run.id}/`) return fulfillApi(route, run);
    if (path === `/runs/${run.id}/usage/`) return fulfillApi(route, { calls: 0, by_item: [] });
    if (path === "/run-items/") return fulfillApi(route, apiPage([]));
    if (path === "/fields/") return fulfillApi(route, apiPage([]));
    if (path === "/classifications/") return fulfillApi(route, apiPage([]));
    if (path === "/labels/") return fulfillApi(route, apiPage(labels));
    if (path === "/workflows/")
      return fulfillApi(route, apiPage(url.searchParams.get("project") === SECOND_PROJECT.id ? [] : [WORKFLOW]));
    if (path === "/workflows/types/")
      return fulfillApi(route, { unbundle_classify_extract: { label: "Unbundle, classify and extract", schema: {} } });
    if (path === "/workflows/capabilities/") return fulfillApi(route, { image_normalization: { available: true } });
    return reject(route);
  });
  return requests;
}

async function storedScope(page: Page) {
  return page.evaluate(() => JSON.parse(localStorage.getItem("docai-working-context") ?? "{}").state);
}

async function staleScope(page: Page) {
  await page.addInitScript(() =>
    localStorage.setItem(
      "docai-working-context",
      JSON.stringify({
        state: { projectId: "project-2", datasetId: "dataset-2" },
        version: 0,
      }),
    ),
  );
}

async function contextControls(page: Page) {
  const mobile = page.viewportSize()!.width < 1024;
  if (mobile && !(await page.getByRole("dialog", { name: "Navigation", exact: true }).isVisible()))
    await page.getByRole("button", { name: "Open navigation", exact: true }).click();
  const container = mobile
    ? page.getByRole("dialog", { name: "Navigation", exact: true })
    : page.locator("#primary-sidebar");
  return {
    container,
    project: container.getByRole("combobox", { name: "Active project", exact: true }),
    dataset: container.getByRole("combobox", { name: "Active dataset", exact: true }),
  };
}

async function expectScope(page: Page, projectId = PROJECT.id, datasetId: string | null = DATASET.id) {
  await expect.poll(() => storedScope(page)).toEqual({ projectId, datasetId });
}

test.use({ viewport: { width: 1440, height: 900 } });

test("a direct document link aligns authorized scope and switching opens its new documents", async ({
  page,
  apiGuard,
}) => {
  await prepareWorkspace(page);
  await staleScope(page);
  const requests = await mockWorkspace(page, apiGuard.reject);
  await page.goto(`/documents/${document.id}?run=${run.id}&from=run`);
  const controls = await contextControls(page);
  await expect(controls.project).toHaveValue(PROJECT.id);
  await expect(controls.dataset).toHaveValue(DATASET.id);
  await expectScope(page);
  await expect(controls.container.getByText(hint, { exact: true })).toBeVisible();
  await expect(controls.project).toHaveAccessibleDescription(hint);
  await expect(controls.dataset).toHaveAccessibleDescription(hint);
  await controls.dataset.selectOption(SIBLING_DATASET.id);
  await expect(page).toHaveURL(/\/datasets$/);
  await expect(page.getByRole("heading", { name: SIBLING_DATASET.name, exact: true })).toBeVisible();
  await expectScope(page, PROJECT.id, SIBLING_DATASET.id);
  await expect
    .poll(() =>
      requests.some(
        ({ url }) => url.pathname === "/api/v1/documents/" && url.searchParams.get("dataset") === SIBLING_DATASET.id,
      ),
    )
    .toBe(true);
  expect(requests.every(({ method }) => method === "GET")).toBe(true);
});

test("a direct run link aligns its scope and switching project opens the new run list", async ({ page, apiGuard }) => {
  await prepareWorkspace(page);
  await staleScope(page);
  const requests = await mockWorkspace(page, apiGuard.reject);
  await page.goto(`/runs/${run.id}?document=${document.id}#items`);
  await expect(page.getByRole("heading", { name: run.name, exact: true })).toBeVisible();
  const controls = await contextControls(page);
  await expect(controls.project).toHaveValue(PROJECT.id);
  await expect(controls.dataset).toHaveValue(DATASET.id);
  await controls.project.selectOption(SECOND_PROJECT.id);
  await expect(page).toHaveURL(/\/runs$/);
  await expectScope(page, SECOND_PROJECT.id, null);
  await expect
    .poll(() =>
      requests.some(
        ({ url }) =>
          url.pathname === "/api/v1/runs/" &&
          url.searchParams.get("project") === SECOND_PROJECT.id &&
          !url.searchParams.has("dataset"),
      ),
    )
    .toBe(true);
  expect(requests.every(({ method }) => method === "GET")).toBe(true);
});

for (const list of [
  { route: "/datasets?page=4&status=processed&q=statement", heading: SIBLING_DATASET.name, endpoint: "/documents/" },
  { route: "/results?run=run-1&page=4&q=statement", heading: "Extracted results", endpoint: "/fields/" },
  { route: "/review?run=run-1&page=4&q=statement", heading: "Review queue", endpoint: "/fields/" },
  { route: "/runs?dataset=dataset-1&workflow=workflow-1&page=4&q=statement", heading: "Runs", endpoint: "/runs/" },
]) {
  test(`${list.route.split("?")[0]} changes scope without old filters or pagination returning`, async ({
    page,
    apiGuard,
  }) => {
    await prepareWorkspace(page);
    const requests = await mockWorkspace(page, apiGuard.reject);
    await page.goto(list.route);
    const controls = await contextControls(page);
    await expect(controls.dataset).toHaveValue(DATASET.id);
    const originalUrl = page.url();
    await controls.dataset.selectOption(DATASET.id);
    await expect(page).toHaveURL(originalUrl);
    await expect(page.getByRole("dialog", { name: dialogName })).not.toBeVisible();
    await controls.dataset.selectOption(SIBLING_DATASET.id);
    await expect(page.getByRole("heading", { name: list.heading, exact: true })).toBeVisible();
    await expect
      .poll(() => {
        const url = new URL(page.url());
        return {
          pathname: url.pathname,
          run: url.searchParams.get("run"),
          dataset: url.searchParams.get("dataset"),
          workflow: url.searchParams.get("workflow"),
          page: url.searchParams.get("page") ?? "1",
          q: url.searchParams.get("q"),
        };
      })
      .toEqual({
        pathname: list.route.split("?")[0],
        run: null,
        dataset: null,
        workflow: null,
        page: "1",
        q: "statement",
      });
    await expect
      .poll(() =>
        requests
          .filter(({ url }) => url.pathname === `/api/v1${list.endpoint}`)
          .at(-1)
          ?.url.searchParams.get("dataset"),
      )
      .toBe(SIBLING_DATASET.id);
    const latest = requests.filter(({ url }) => url.pathname === `/api/v1${list.endpoint}`).at(-1)!.url;
    expect(latest.searchParams.get("page")).toBe("1");
    expect(latest.searchParams.has("run")).toBe(false);
    await expect(controls.dataset).toHaveValue(SIBLING_DATASET.id);
    await expectScope(page, PROJECT.id, SIBLING_DATASET.id);
  });
}

test("a late document response cannot restore the departing scope", async ({ page, apiGuard }) => {
  await prepareWorkspace(page);
  let release!: () => void;
  const documentGate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const requests = await mockWorkspace(page, apiGuard.reject, { documentGate });
  await page.goto(`/documents/${document.id}?run=${run.id}`);
  await expect.poll(() => requests.some(({ url }) => url.pathname === `/api/v1/documents/${document.id}/`)).toBe(true);
  const controls = await contextControls(page);
  await controls.project.selectOption(SECOND_PROJECT.id);
  await expect(page).toHaveURL(/\/datasets$/);
  release();
  await expect(page.getByRole("heading", { name: "Datasets & documents", exact: true })).toBeVisible();
  await expectScope(page, SECOND_PROJECT.id, null);
  await expect(controls.project).toHaveValue(SECOND_PROJECT.id);
});

test("an inaccessible document does not align context from an unauthorized response", async ({ page, apiGuard }) => {
  await prepareWorkspace(page);
  await staleScope(page);
  const requests = await mockWorkspace(page, apiGuard.reject, { documentStatus: 403 });
  await page.goto(`/documents/${document.id}?run=${run.id}`);
  await expect(page.getByRole("button", { name: "Retry", exact: true })).toBeVisible();
  await expectScope(page, SECOND_PROJECT.id, SECOND_DATASET.id);
  expect(requests.some(({ url }) => url.pathname === `/api/v1/datasets/${DATASET.id}/`)).toBe(false);
});

for (const theme of ["light", "dark"] as const) {
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
    { width: 1440, height: 900 },
    { width: 720, height: 450 },
  ]) {
    test(`unsaved labels retain draft on Cancel and Escape, then discard · ${theme} · ${viewport.width}`, async ({
      page,
      apiGuard,
    }, testInfo) => {
      await page.setViewportSize(viewport);
      await prepareWorkspace(page, E2E_USER.username, theme);
      const requests = await mockWorkspace(page, apiGuard.reject);
      await page.goto(`/labeling/${document.id}?run=${run.id}&from=run`);
      await page.getByLabel("Field name", { exact: false }).fill("missing_value");
      await page.getByLabel("Expected value", { exact: true }).fill("Draft expected value");
      await page.getByLabel("Notes", { exact: true }).fill("Checked source");
      const originalUrl = page.url();
      const controls = await contextControls(page);
      await expect(controls.project).toHaveAccessibleDescription(hint);
      await expect(controls.dataset).toHaveAccessibleDescription(hint);
      await page.screenshot({ path: testInfo.outputPath("workspace-hint.png") });
      await controls.dataset.focus();
      await controls.dataset.selectOption(SIBLING_DATASET.id);
      const dialog = page.getByRole("dialog", { name: dialogName, exact: true });
      const cancel = dialog.getByRole("button", { name: "Cancel", exact: true });
      await expect(dialog).toBeVisible();
      await expect(cancel).toBeFocused();
      await expect(controls.project).toHaveValue(PROJECT.id);
      await expect(controls.dataset).toHaveValue(DATASET.id);
      await expectScope(page);
      if (viewport.width < 1024) await expect(controls.container).toHaveAttribute("open", "");
      await page.keyboard.press("Tab");
      await expect(dialog.getByRole("button", { name: "Discard and switch", exact: true })).toBeFocused();
      await controls.dataset.evaluate((element) => element.focus());
      expect(await dialog.evaluate((element) => element.contains(window.document.activeElement))).toBe(true);
      expect((await new AxeBuilder({ page }).include("dialog[open][aria-labelledby]").analyze()).violations).toEqual(
        [],
      );
      const box = await dialog.locator(".modal-box").boundingBox();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.y).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
      expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
      expect(await page.evaluate(() => window.document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath("discard-dialog.png") });
      await cancel.click();
      await expect(dialog).not.toBeVisible();
      await expect(controls.dataset).toBeFocused();
      await expect(page).toHaveURL(originalUrl);
      await expectScope(page);
      expect(
        (
          await new AxeBuilder({ page })
            .include(viewport.width < 1024 ? "#tour-mobile-working-context" : "#tour-working-context")
            .analyze()
        ).violations,
      ).toEqual([]);
      await controls.dataset.selectOption(SIBLING_DATASET.id);
      await expect(dialog).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(dialog).not.toBeVisible();
      await expect(controls.dataset).toBeFocused();
      if (viewport.width < 1024) {
        await expect(controls.container).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(controls.container).not.toBeVisible();
      }
      await expect(page.getByLabel("Field name", { exact: false })).toHaveValue("missing_value");
      await expect(page.getByLabel("Expected value", { exact: true })).toHaveValue("Draft expected value");
      await expect(page.getByLabel("Notes", { exact: true })).toHaveValue("Checked source");
      await expect(page).toHaveURL(originalUrl);
      await expectScope(page);
      const reopened = await contextControls(page);
      await reopened.project.selectOption(SECOND_PROJECT.id);
      await dialog.getByRole("button", { name: "Discard and switch", exact: true }).click();
      await expect(page).toHaveURL(/\/datasets$/);
      await expectScope(page, SECOND_PROJECT.id, null);
      await expect(dialog).not.toBeVisible();
      expect(requests.every(({ method }) => method === "GET")).toBe(true);
    });
  }
}

test("validation keeps configuration dirty and Cancel preserves both form and JSON", async ({ page, apiGuard }) => {
  await prepareWorkspace(page);
  const requests = await mockWorkspace(page, apiGuard.reject, { validate: true });
  await page.goto("/workflows/new");
  await page.getByLabel("Name", { exact: false }).fill("Draft extraction");
  const json = '{ "categories": [], "schemas": [], "other_behavior": "needs_review" }';
  await page.getByLabel("Type-specific configuration JSON").fill(json);
  await page.getByRole("button", { name: "Validate", exact: true }).click();
  await expect(page.getByText("Valid · hash", { exact: false })).toBeVisible();
  const controls = await contextControls(page);
  await controls.project.selectOption(SECOND_PROJECT.id);
  const dialog = page.getByRole("dialog", { name: dialogName, exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page).toHaveURL(/\/workflows\/new$/);
  await expectScope(page);
  await expect(controls.project).toHaveValue(PROJECT.id);
  await expect(controls.dataset).toHaveValue(DATASET.id);
  await expect(page.getByLabel("Name", { exact: false })).toHaveValue("Draft extraction");
  await expect(page.getByLabel("Type-specific configuration JSON")).toHaveValue(json);
  await controls.project.selectOption(SECOND_PROJECT.id);
  await dialog.getByRole("button", { name: "Discard and switch", exact: true }).click();
  await expect(page).toHaveURL(/\/configurations$/);
  await expectScope(page, SECOND_PROJECT.id, null);
  expect(requests.filter(({ method }) => method !== "GET").map(({ url }) => url.pathname)).toEqual([
    "/api/v1/workflows/validate/",
  ]);
});

test("a pristine configuration switches without a discard prompt", async ({ page, apiGuard }) => {
  await prepareWorkspace(page);
  await mockWorkspace(page, apiGuard.reject);
  await page.goto("/workflows/new");
  await expect(page.getByLabel("Type-specific configuration JSON")).toBeVisible();
  const controls = await contextControls(page);
  await controls.project.selectOption(SECOND_PROJECT.id);
  await expect(page).toHaveURL(/\/configurations$/);
  await expect(page.getByRole("dialog", { name: dialogName, exact: true })).not.toBeVisible();
});

for (const labelSave of ["success", "failure"] as const) {
  test(`a ${labelSave === "success" ? "saved" : "failed"} absent label ${labelSave === "success" ? "clears" : "retains"} the workspace guard`, async ({
    page,
    apiGuard,
  }) => {
    await prepareWorkspace(page);
    const requests = await mockWorkspace(page, apiGuard.reject, { labelSave });
    await page.goto(`/labeling/${document.id}?run=${run.id}`);
    await page.getByLabel("Field name", { exact: false }).fill("missing_value");
    await page.getByLabel("Notes", { exact: true }).fill("Checked source");
    const response = page.waitForResponse(
      (item) => item.url().endsWith("/labels/") && item.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Mark absent", exact: true }).click();
    await response;
    await expect(page.getByRole("button", { name: "Mark absent", exact: true })).toBeEnabled();
    const controls = await contextControls(page);
    await controls.dataset.selectOption(SIBLING_DATASET.id);
    const dialog = page.getByRole("dialog", { name: dialogName, exact: true });
    if (labelSave === "success") {
      await expect(page).toHaveURL(/\/datasets$/);
      await expect(dialog).not.toBeVisible();
    } else {
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
      await expect(page.getByLabel("Field name", { exact: false })).toHaveValue("missing_value");
      await expect(page.getByLabel("Notes", { exact: true })).toHaveValue("Checked source");
      await expectScope(page);
    }
    expect(requests.filter(({ method }) => method === "POST")).toHaveLength(1);
  });
}
