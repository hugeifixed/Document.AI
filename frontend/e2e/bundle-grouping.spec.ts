import AxeBuilder from "@axe-core/playwright";
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

for (const theme of ["light", "dark"] as const) {
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
    { width: 1440, height: 900 },
  ]) {
    test(`grouping review remains visible without flagged fields · ${theme} · ${viewport.width}`, async ({
      page,
      apiGuard,
    }) => {
      await page.setViewportSize(viewport);
      await prepareWorkspace(page, E2E_USER.username, theme);
      await page.route("**/api/v1/**", async (route) => {
        const url = new URL(route.request().url());
        const path = url.pathname.replace("/api/v1", "");
        if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
        if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
        if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
        if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
        if (path === "/fields/" || path === "/classifications/") return fulfillApi(route, apiPage([]));
        if (path === "/segments/") {
          expect(url.searchParams.get("run")).toBe(RUN.id);
          expect(url.searchParams.get("review_status")).toBe("needs_review");
          return fulfillApi(
            route,
            apiPage([
              {
                id: "segment-2",
                run: RUN.id,
                document: DOCUMENT.id,
                document_name: DOCUMENT.original_filename,
                index: 1,
                start_unit: 2,
                end_unit: 17,
                category: "promissory_note",
                score: null,
                method: "segmentation",
                review_status: "needs_review",
                boundary_review_reasons: ["SEGMENTATION_BOUNDARY_REPAIRED"],
              },
            ]),
          );
        }
        return apiGuard.reject(route);
      });
      await page.goto(`/review?run=${RUN.id}`);
      await expect(page.getByText("promissory_note · Document 2 · Pages 3–18")).toBeVisible();
      const why = page.getByText("Why and how to resolve", { exact: true });
      await why.focus();
      await page.keyboard.press("Enter");
      await expect(page.getByText(/Accepting a field or classification does not approve this grouping/)).toBeVisible();
      await expect(page.getByRole("link", { name: "Inspect grouping" })).toHaveAttribute(
        "href",
        `/review/${DOCUMENT.id}?run=${RUN.id}&from=review`,
      );
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    });
  }
}
