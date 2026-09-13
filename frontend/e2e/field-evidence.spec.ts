import AxeBuilder from "@axe-core/playwright";
import { Buffer } from "node:buffer";
import type { Locator, Page } from "@playwright/test";
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

// Real two-page PDF with synthetic text. Exercises PDF.js rendering without a binary fixture.
function evidencePdf() {
  const text = "BT /F1 14 Tf 478 145 Td (Evidence) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    `<< /Length ${Buffer.byteLength(text)} >>\nstream\n${text}\nendstream`,
  ];
  let pdf = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const startxref = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  pdf += offsets.map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${startxref}\n%%EOF`;
  return Buffer.from(pdf);
}

const evidenceField = {
  ...FIELD,
  name: "reference_number",
  raw_value: "Evidence",
  normalized_value: "Evidence",
  source_text: "Evidence",
  spans: [
    {
      id: "span-1",
      unit_index: 1,
      unit_kind: "page",
      text: "Evidence",
      polygon: [0.78, 0.8, 0.95, 0.8, 0.95, 0.84, 0.78, 0.84],
      word_ids: ["p2:w0"],
      cell_range: "",
      mapping_method: "exact",
      match_score: 1,
      offset_start: 0,
      offset_end: 8,
    },
  ],
};
const unlocatedField = { ...FIELD, id: "field-unlocated", name: "unlocated_number", source_text: "", grounded: false };
const completedRun = { ...RUN, status: "succeeded", stage: "complete", processed_items: 1 };
const evidenceDocument = {
  ...DOCUMENT,
  original_filename: "evidence-example.pdf",
  file_format: "pdf",
  page_count: 2,
  units: [0, 1].map((index) => ({
    id: `unit-${index}`,
    index,
    kind: "page",
    label: `Page ${index + 1}`,
    width: 612,
    height: 792,
    unit: "pt",
  })),
  processing_source: {
    is_original: false,
    file_format: "pdf",
    url: `/api/v1/documents/${DOCUMENT.id}/processing-source/?run=${RUN.id}`,
    layout_artifact: "layout-1",
  },
};

async function expectEvidenceVisible(page: Page, overlay: Locator) {
  await expect(overlay).toBeVisible();
  await expect
    .poll(async () =>
      overlay.evaluate((element) => {
        const box = element.getBoundingClientRect();
        return box.top >= 64 && box.left >= 0 && box.bottom <= innerHeight && box.right <= innerWidth;
      }),
    )
    .toBe(true);
  // It must also lie inside each scrollable ancestor, not merely the window bounds.
  await expect
    .poll(async () =>
      overlay.evaluate((element) => {
        const box = element.getBoundingClientRect();
        for (let parent = element.parentElement; parent; parent = parent.parentElement) {
          const style = getComputedStyle(parent);
          if (/auto|scroll|hidden/.test(style.overflowX) && parent.scrollWidth > parent.clientWidth) {
            const bounds = parent.getBoundingClientRect();
            if (box.left < bounds.left - 1 || box.right > bounds.right + 1) return false;
          }
        }
        return true;
      }),
    )
    .toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
}

for (const theme of ["light", "dark"] as const) {
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1024, height: 768 },
    { width: 1440, height: 900 },
  ]) {
    test(`field evidence navigation · ${theme} · ${viewport.width}`, async ({ page, apiGuard }, testInfo) => {
      test.setTimeout(60_000);
      await page.setViewportSize(viewport);
      await page.emulateMedia({ reducedMotion: "no-preference" });
      await prepareWorkspace(page, E2E_USER.username, theme);
      await page.addInitScript(() => {
        (window as Window & { evidenceAnimations: string[] }).evidenceAnimations = [];
        document.addEventListener("animationstart", (event) => {
          if (event.target instanceof Element && event.target.closest(".overlay-box")) {
            (window as Window & { evidenceAnimations: string[] }).evidenceAnimations.push(event.animationName);
          }
        });
      });
      await page.route("**/api/v1/**", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const path = url.pathname.replace("/api/v1", "");
        if (path === "/auth/session/") return fulfillApi(route, { user: E2E_USER });
        if (path === "/dashboard/") return fulfillApi(route, DASHBOARD);
        if (path === "/projects/") return fulfillApi(route, apiPage([PROJECT]));
        if (path === "/datasets/") return fulfillApi(route, apiPage([DATASET]));
        if (path === "/runs/") return fulfillApi(route, apiPage([completedRun]));
        if (path === "/run-items/")
          return fulfillApi(
            route,
            apiPage([
              {
                id: "item-1",
                run: RUN.id,
                document: DOCUMENT.id,
                status: "succeeded",
                stage: "done",
                attempts: 1,
                error_code: "",
                error_message: "",
                retryable: false,
                duration_ms: 300,
                modified: RUN.created,
              },
            ]),
          );
        if (path === "/fields/") return fulfillApi(route, apiPage([evidenceField, unlocatedField]));
        if (path === "/labels/") return fulfillApi(route, apiPage([]));
        if (path === `/documents/${DOCUMENT.id}/`) return fulfillApi(route, evidenceDocument);
        if (/\/documents\/document-1\/units\/\d\//.test(path)) {
          const index = Number(path.split("/").at(-2));
          return fulfillApi(route, {
            kind: "page",
            index,
            number: index + 1,
            width: 612,
            height: 792,
            unit: "pt",
            content: "Evidence",
            has_text_layer: true,
            words: [],
          });
        }
        if (path === `/documents/${DOCUMENT.id}/original/` || path === `/documents/${DOCUMENT.id}/processing-source/`) {
          return route.fulfill({ contentType: "application/pdf", body: evidencePdf() });
        }
        return apiGuard.reject(route);
      });
      await page.goto(`/documents/${DOCUMENT.id}?run=${RUN.id}&from=run`);
      const pageSelect = page.getByRole("combobox", { name: "Page", exact: true });
      await expect(page.locator('.react-pdf__Page[data-page-number="1"] canvas')).toBeVisible();
      const field = page.getByRole("button", { name: /reference_number/ });
      const overlay = page.locator(".overlay-box.selected").first();
      await field.click();
      await expect(pageSelect).toHaveValue("1");
      await expect(page.locator('.react-pdf__Page[data-page-number="2"] canvas')).toBeVisible();
      await expectEvidenceVisible(page, overlay);
      await expect(field).toBeFocused();
      expect(new URL(page.url()).searchParams.get("run")).toBe(RUN.id);
      expect(new URL(page.url()).searchParams.get("from")).toBe("run");
      expect(new URL(page.url()).searchParams.get("field")).toBe(FIELD.id);
      await expect
        .poll(() =>
          page.evaluate(() => (window as Window & { evidenceAnimations: string[] }).evidenceAnimations.length),
        )
        .toBeGreaterThan(0);
      // Theme colours must remain distinguishable on the white document canvas.
      const outlineContrast = await overlay.evaluate((element) => {
        const canvas = window.document.createElement("canvas");
        canvas.width = canvas.height = 1;
        const context = canvas.getContext("2d")!;
        context.fillStyle = getComputedStyle(element).outlineColor;
        context.fillRect(0, 0, 1, 1);
        const rgb = Array.from(context.getImageData(0, 0, 1, 1).data)
          .slice(0, 3)
          .map((channel) => {
            const value = channel / 255;
            return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
          });
        return 1.05 / (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2] + 0.05);
      });
      expect(outlineContrast).toBeGreaterThanOrEqual(3);
      await page.screenshot({ path: testInfo.outputPath("located-evidence.png") });

      // A repeat selection after manual page browsing must re-locate, including via keyboard.
      const previousEmphasis = await page.evaluate(
        () => (window as Window & { evidenceAnimations: string[] }).evidenceAnimations.length,
      );
      await pageSelect.selectOption("0");
      await expect(page.locator('.react-pdf__Page[data-page-number="1"] canvas')).toBeVisible();
      await field.focus();
      await page.keyboard.press("Enter");
      await expect(pageSelect).toHaveValue("1");
      await expectEvidenceVisible(page, overlay);
      await expect(field).toBeFocused();

      await expect
        .poll(() =>
          page.evaluate(() => (window as Window & { evidenceAnimations: string[] }).evidenceAnimations.length),
        )
        .toBeGreaterThan(previousEmphasis);

      await page.getByRole("button", { name: "View original", exact: true }).click();
      await expect(page.locator(".overlay-box")).toHaveCount(0);
      await field.click();
      await expect(page.getByRole("button", { name: "View original", exact: true })).toBeAttached();
      await expectEvidenceVisible(page, overlay);

      await page.getByRole("button", { name: /unlocated_number/ }).click();
      await expect(pageSelect).toHaveValue("1");
      await expect(page.locator(".overlay-box.selected")).toHaveCount(0);
      await expect(page.getByText(/no .*location|location .*available|not .*located/i).first()).toBeVisible();

      await page.emulateMedia({ reducedMotion: "reduce" });
      if (viewport.width === 1440) await page.setViewportSize({ width: 720, height: 450 });
      await page.evaluate(() => {
        (window as Window & { evidenceAnimations: string[] }).evidenceAnimations = [];
      });
      await field.click();
      await expectEvidenceVisible(page, overlay);
      expect(await overlay.evaluate((element) => getComputedStyle(element).animationName)).toBe("none");
      expect(
        await page.evaluate(() => (window as Window & { evidenceAnimations: string[] }).evidenceAnimations),
      ).toEqual([]);
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
      await page.screenshot({ path: testInfo.outputPath("reduced-motion-evidence.png") });

      // A shared field link must locate after a cold PDF load as well.
      await page.reload();
      await expect(pageSelect).toHaveValue("1");
      await expectEvidenceVisible(page, overlay);
    });
  }
}
