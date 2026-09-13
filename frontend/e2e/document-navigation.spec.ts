import AxeBuilder from "@axe-core/playwright";
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
    test(`browse adjacent documents within a run · ${theme} · ${viewport.width}`, async ({
      page,
      apiGuard,
    }, testInfo) => {
      await page.setViewportSize(viewport);
      await prepareWorkspace(page, E2E_USER.username, theme);
      const secondId = "document-2";
      const secondName = "second-statement.txt";
      const requests: { document: string; run: string | null }[] = [];
      await page.route("**/api/v1/**", (route) => {
        const url = new URL(route.request().url());
        const path = url.pathname.replace("/api/v1", "");
        if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
        if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
        if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
        if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
        if (path === `/datasets/${DATASET.id}/`) return fulfillApi(route, DATASET);
        if (path === `/projects/${PROJECT.id}/`) return fulfillApi(route, PROJECT);
        if (path === "/runs/") return fulfillApi(route, apiPage([RUN]));
        if (path === "/run-items/")
          return fulfillApi(
            route,
            apiPage([
              {
                id: "item-1",
                run: RUN.id,
                document: url.searchParams.get("document"),
                status: "succeeded",
                stage: "complete",
                attempts: 1,
                error_code: "",
                error_message: "",
                retryable: false,
              },
            ]),
          );
        if (path === "/fields/")
          return fulfillApi(route, apiPage(url.searchParams.get("document") === DOCUMENT.id ? [FIELD] : []));
        if (path === "/labels/") return fulfillApi(route, apiPage([]));
        const match = path.match(/^\/documents\/(document-[12])\/$/);
        if (match) {
          const second = match[1] === secondId;
          requests.push({ document: match[1], run: url.searchParams.get("run") });
          return fulfillApi(route, {
            ...DOCUMENT,
            id: match[1],
            original_filename: second ? secondName : DOCUMENT.original_filename,
            units: second
              ? DOCUMENT.units
              : [...DOCUMENT.units, { ...DOCUMENT.units[0], id: "unit-2", index: 1, label: "Page 2" }],
            navigation: {
              scope: "run",
              run: RUN.id,
              previous: second ? { id: DOCUMENT.id, original_filename: DOCUMENT.original_filename } : null,
              next: second ? null : { id: secondId, original_filename: secondName },
            },
          });
        }
        const unit = path.match(/^\/documents\/document-[12]\/units\/(\d)\/$/);
        if (unit) return fulfillApi(route, { kind: "page", index: Number(unit[1]), content: "Statement text" });
        return apiGuard.reject(route);
      });
      await page.goto(`/documents/${DOCUMENT.id}?run=${RUN.id}&from=results&field=${FIELD.id}`);
      const nav = page.getByRole("navigation", { name: "Document navigation" });
      await expect(nav.getByRole("button", { name: "Previous document" })).toBeDisabled();
      await page.getByRole("combobox", { name: "Page", exact: true }).selectOption("1");
      const next = nav.getByRole("link", { name: `Next document: ${secondName}` });
      await expect(next).toHaveAttribute("href", `/documents/${secondId}?run=${RUN.id}&from=results`);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect((await new AxeBuilder({ page }).include("main").analyze()).violations).toEqual([]);
      await nav.screenshot({ path: testInfo.outputPath("document-navigation.png") });
      await next.focus();
      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(`/documents/${secondId}?run=${RUN.id}&from=results`);
      await expect(page.getByRole("heading", { name: secondName, exact: true })).toBeVisible();
      await expect(page.getByRole("combobox", { name: "Page", exact: true })).toHaveValue("0");
      await expect(nav.getByRole("button", { name: "Next document" })).toBeDisabled();
      const previous = nav.getByRole("link", { name: `Previous document: ${DOCUMENT.original_filename}` });
      await previous.click();
      await expect(page).toHaveURL(`/documents/${DOCUMENT.id}?run=${RUN.id}&from=results`);
      expect(requests.every(({ run }) => run === RUN.id)).toBe(true);
      await page.goBack();
      await expect(page).toHaveURL(`/documents/${secondId}?run=${RUN.id}&from=results`);
    });
  }
}
