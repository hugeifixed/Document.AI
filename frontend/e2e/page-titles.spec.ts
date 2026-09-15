import type { Page, Route } from "@playwright/test";
import {
  apiPage,
  DASHBOARD,
  DATASET,
  DOCUMENT,
  E2E_USER,
  FIELD,
  fulfillApi,
  prepareWorkspace,
  PROJECT,
} from "./support/api";
import { expect, test } from "./support/test";

const environment = (process.env.VITE_DEPLOYMENT_ENV?.trim() || "DEV").toUpperCase();
const prefix = ["PROD", "PRODUCTION"].includes(environment) ? "" : `[${environment}] `;
const application = process.env.VITE_APPLICATION_NAME?.trim() || "Document AI";
const title = (label: string) => `${prefix}${label} | ${application}`;

test.use({ viewport: { width: 1440, height: 900 } });

async function mockPages(
  page: Page,
  reject: (route: Route) => Promise<void>,
  options: {
    sessionGate?: Promise<void>;
    fieldsGate?: Promise<void>;
    user?: typeof E2E_USER | null;
    fieldStatus?: number;
    documentStatus?: number;
    fields?: boolean;
  } = {},
) {
  await prepareWorkspace(page);
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === "/auth/session/") {
      await options.sessionGate;
      return fulfillApi(route, { user: options.user === undefined ? E2E_USER : options.user });
    }
    if (path === "/workflows/types/") return fulfillApi(route, {});
    if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
    if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
    if (path === `/projects/${PROJECT.id}/`) return fulfillApi(route, PROJECT);
    if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
    if (path === `/datasets/${DATASET.id}/`) return fulfillApi(route, DATASET);
    if (path === `/documents/${DOCUMENT.id}/`) return fulfillApi(route, DOCUMENT, options.documentStatus ?? 200);
    if (path === `/documents/${DOCUMENT.id}/units/0/`)
      return fulfillApi(route, { kind: "page", index: 0, content: "Private document text" });
    if (path === "/fields/") {
      await options.fieldsGate;
      return fulfillApi(route, apiPage(options.fields ? [FIELD] : []), options.fieldStatus ?? 200);
    }
    if (["/runs/", "/run-items/", "/labels/", "/documents/", "/classifications/", "/categories/"].includes(path))
      return fulfillApi(route, apiPage([]));
    return reject(route);
  });
}

test("direct entry has its title before session and data load, then retains it for empty data", async ({
  page,
  apiGuard,
}) => {
  let releaseSession!: () => void;
  let releaseFields!: () => void;
  const sessionGate = new Promise<void>((resolve) => {
    releaseSession = resolve;
  });
  const fieldsGate = new Promise<void>((resolve) => {
    releaseFields = resolve;
  });
  await mockPages(page, apiGuard.reject, { sessionGate, fieldsGate });
  await page.goto("/review?customer=private-customer&account=123456", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveTitle(title("Review Queue"));
  releaseSession();
  await expect(page.getByRole("heading", { name: "Review queue", exact: true })).toBeVisible();
  await expect(page).toHaveTitle(title("Review Queue"));
  releaseFields();
  await expect(page.getByText("No extracted fields need review in this context.", { exact: true })).toBeVisible();
  await expect(page).toHaveTitle(title("Review Queue"));
});

test("navigation, refresh, Back and Forward keep static titles and exclude sensitive content", async ({
  page,
  apiGuard,
}) => {
  await mockPages(page, apiGuard.reject, { fields: true });
  await page.goto("/review");
  await expect(page).toHaveTitle(title("Review Queue"));
  await page
    .getByRole("navigation", { name: "Primary", exact: true })
    .getByRole("link", { name: "Extracted results", exact: true })
    .click();
  await expect(page).toHaveTitle(title("Extraction Results"));
  await expect(page.getByText(FIELD.raw_value).first()).toBeVisible();
  await page.goBack();
  await expect(page).toHaveTitle(title("Review Queue"));
  await page.goForward();
  await expect(page).toHaveTitle(title("Extraction Results"));
  await page.goto(`/documents/${DOCUMENT.id}?account=123456&customer=private-customer`);
  await expect(page).toHaveTitle(title("Extraction Results"));
  await page.reload();
  await expect(page).toHaveTitle(title("Extraction Results"));
  await expect(page.getByText(DOCUMENT.original_filename, { exact: true }).first()).toBeVisible();
  const browserTitle = await page.title();
  for (const sensitive of [FIELD.raw_value, DOCUMENT.original_filename, DOCUMENT.id, "123456", "private-customer"])
    expect(browserTitle).not.toContain(sensitive);
});

test("sign-in and unknown routes have their own titles", async ({ page, apiGuard }) => {
  await mockPages(page, apiGuard.reject, { user: null });
  await page.goto("/review?private=123456");
  await expect(page.getByRole("heading", { name: "Sign in to DocAI" })).toBeVisible();
  await expect(page).toHaveTitle(title("Sign In"));
  await page.unroute("**/api/v1/**");
  await mockPages(page, apiGuard.reject);
  await page.goto("/unknown-private-file");
  await expect(page.getByRole("heading", { name: "Page not found", exact: true })).toBeVisible();
  await expect(page).toHaveTitle(title("Page Not Found"));
  await page.getByRole("link", { name: "Dashboard", exact: true }).last().click();
  await expect(page).toHaveTitle(title("Workspace"));
});

test("failed table retrieval retains the route title", async ({ page, apiGuard }) => {
  await mockPages(page, apiGuard.reject, { fieldStatus: 500 });
  await page.goto("/results");
  await expect(page.getByRole("button", { name: /retry/i }).first()).toBeVisible();
  await expect(page).toHaveTitle(title("Extraction Results"));
});

for (const path of ["/labeling", "/workflows/new", `/labeling/${DOCUMENT.id}`, `/documents/${DOCUMENT.id}`]) {
  test(`denied existing view ${path} declares Access Denied`, async ({ page, apiGuard }) => {
    await mockPages(page, apiGuard.reject, { user: { ...E2E_USER, roles: [] } });
    await page.goto(path);
    await expect(page).toHaveTitle(title("Access Denied"));
    await expect(page.getByText(/requires the/).first()).toBeVisible();
    await page
      .getByRole("navigation", { name: "Primary", exact: true })
      .getByRole("link", { name: "Extracted results", exact: true })
      .click();
    await expect(page).toHaveTitle(title("Extraction Results"));
  });
}

for (const [status, label] of [
  [403, "Access Denied"],
  [404, "Page Not Found"],
  [500, "Page Error"],
] as const) {
  test(`document error ${status} has a safe title`, async ({ page, apiGuard }) => {
    await mockPages(page, apiGuard.reject, { documentStatus: status });
    await page.goto(`/documents/${DOCUMENT.id}`);
    await expect(page.getByRole("alert").first()).toBeVisible();
    await expect(page).toHaveTitle(title(label));
  });
}
