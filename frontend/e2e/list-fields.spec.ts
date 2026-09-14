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
for (const viewport of [{width:390,height:844},{width:768,height:1024},{width:1024,height:768},{width:1440,height:900}]) {
test(`collection review · ${theme} · ${viewport.width}`, async ({page,apiGuard},testInfo) => {
  let reviewBody: unknown;
  await page.setViewportSize(viewport);
  await prepareWorkspace(page, E2E_USER.username, theme);
  const collection = {...FIELD, name: "state_and_local_entries", field_type: "list", raw_value: JSON.stringify([{state:"AK",employer_state_id:"001",state_wages:"12.30",state_tax:"1.20",local_wages:"12.30",local_tax:"1.20",locality:"Long locality name for wrapping checks"}, {state:"DE",employer_state_id:"002",state_wages:"24.60",state_tax:"2.40",local_wages:"24.60",local_tax:"2.40",locality:"Another locality"}]), normalized_value:null, grounded:false,spans:[],review_status:"needs_review",validation_status:"warning",validation_messages:["Verify every list entry against the document."]};
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
    if (path === "/fields/") return fulfillApi(route, apiPage([collection]));
    if (path === "/labels/") return fulfillApi(route, apiPage([]));
    if (path === `/fields/${FIELD.id}/review/` && request.method() === "POST") {
      reviewBody = request.postDataJSON();
      return fulfillApi(route, { ...collection, reviewed_value: "[]", review_status: "corrected" });
    }
    return apiGuard.reject(route);
  });

  await page.goto(`/review/${DOCUMENT.id}?run=${RUN.id}`);
  const table = page.getByRole("table", {name:"state_and_local_entries"});
  await expect(table).toBeVisible();
  await expect(table.getByText("001")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const region=page.getByRole("region", {name:"state_and_local_entries entries"});
  await region.focus();
  await expect(region).toBeFocused();
  expect((await new AxeBuilder({page}).include("main").analyze()).violations).toEqual([]);
  await page.screenshot({path:testInfo.outputPath("collection.png"), fullPage:true});
  await page.getByRole("button", {name:"Correct",exact:true}).click();
  const editor=page.getByRole("textbox",{name:"Corrected value"});
  await expect(editor).toBeFocused();
  await editor.fill("{}");
  await expect(page.getByRole("button",{name:"Save correction"})).toBeDisabled();
  expect((await new AxeBuilder({page}).include("dialog").analyze()).violations).toEqual([]);
  await editor.fill("[]");
  await page.getByRole("button",{name:"Save correction"}).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  expect(reviewBody).toEqual({action:"correct",value:"[]",reason:"Corrected in review workspace"});
});
}
}
