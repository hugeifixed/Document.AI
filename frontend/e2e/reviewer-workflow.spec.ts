import AxeBuilder from "@axe-core/playwright";
import {
  apiPage,
  CLASSIFICATION,
  DASHBOARD,
  DATASET,
  DOCUMENT,
  E2E_USER,
  FIELD,
  fulfillApi,
  prepareWorkspace,
  PROJECT,
  RUN,
} from "./support/api";
import { expect, test } from "./support/test";

test("reviews and corrects an extracted field through the native dialog", async ({ page, apiGuard }) => {
  let reviewBody: unknown;
  await prepareWorkspace(page);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
    if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
    if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
    if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
    if (path === `/datasets/${DATASET.id}/` && request.method() === "GET") return fulfillApi(route, DATASET);
    if (path === `/projects/${PROJECT.id}/` && request.method() === "GET") return fulfillApi(route, PROJECT);
    if (path === `/documents/${DOCUMENT.id}/`) return fulfillApi(route, DOCUMENT);
    if (path === `/documents/${DOCUMENT.id}/units/0/`) {
      return fulfillApi(route, { kind: "page", index: 0, content: "Account holder: Daniel Silva" });
    }
    if (path === "/run-items/") {
      return fulfillApi(
        route,
        apiPage([
          {
            id: "item-1",
            run: RUN.id,
            document: DOCUMENT.id,
            document_name: DOCUMENT.original_filename,
            status: "succeeded",
            stage: "complete",
            attempts: 1,
            error_code: "",
            error_message: "",
            retryable: false,
            duration_ms: 250,
            correlation_id: "correlation-1",
            modified: "2026-09-11T12:00:00Z",
          },
        ]),
      );
    }
    if (path === "/runs/") return fulfillApi(route, apiPage([RUN]));
    if (path === "/segments/") return fulfillApi(route, apiPage([]));
    if (path === "/fields/") return fulfillApi(route, apiPage([FIELD]));
    if (path === "/labels/") return fulfillApi(route, apiPage([]));
    if (path === `/fields/${FIELD.id}/review/` && request.method() === "POST") {
      reviewBody = request.postDataJSON();
      return fulfillApi(route, { ...FIELD, reviewed_value: "Danielle Silva", review_status: "corrected" });
    }
    return apiGuard.reject(route);
  });

  await page.goto(`/review/${DOCUMENT.id}?run=${RUN.id}`);
  const correct = page.getByRole("button", { name: "Correct value" });
  await correct.click();
  const dialog = page.getByRole("dialog", { name: "Correct extracted value" });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Corrected value" })).toBeFocused();
  expect((await new AxeBuilder({ page }).include("dialog").analyze()).violations).toEqual([]);

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(correct).toBeFocused();

  await correct.click();
  await page.getByRole("textbox", { name: "Corrected value" }).fill("Danielle Silva");
  await page.getByRole("button", { name: "Save correction" }).click();
  await expect(dialog).toBeHidden();
  expect(reviewBody).toEqual({ action: "correct", value: "Danielle Silva", reason: "Corrected in review workspace" });
});

test("shows and accepts classification-only review work", async ({ page, apiGuard }) => {
  let acceptBody: unknown;
  await prepareWorkspace(page);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
    if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
    if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
    if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
    if (path === "/segments/") return fulfillApi(route, apiPage([]));
    if (path === "/fields/") return fulfillApi(route, apiPage([]));
    if (path === "/classifications/") return fulfillApi(route, apiPage([CLASSIFICATION]));
    if (path === "/categories/") return fulfillApi(route, apiPage([]));
    if (path === `/classifications/${CLASSIFICATION.id}/accept/` && request.method() === "POST") {
      acceptBody = request.postDataJSON();
      return fulfillApi(route, {
        ...CLASSIFICATION,
        reviewed_category: CLASSIFICATION.category,
        review_status: "accepted",
      });
    }
    return apiGuard.reject(route);
  });

  await page.goto(`/review?run=${RUN.id}`);
  await expect(page.getByRole("link", { name: DOCUMENT.original_filename })).toBeVisible();
  await expect(page.getByText("other", { exact: true })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Accept", exact: true }).click();
  await expect.poll(() => acceptBody).toEqual({ reason: "Accepted in review queue" });
});
