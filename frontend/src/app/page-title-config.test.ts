import { createPageTitleConfig, fallbackTitleHtml, formatPageTitle } from "./page-title-config";

it.each([
  ["prod", "Review Queue | Document AI"],
  [" production ", "Review Queue | Document AI"],
  ["uat", "[UAT] Review Queue | Document AI"],
  ["dev", "[DEV] Review Queue | Document AI"],
  ["QA", "[QA] Review Queue | Document AI"],
  ["", "[DEV] Review Queue | Document AI"],
  [undefined, "[DEV] Review Queue | Document AI"],
])("formats the explicit deployment environment %s", (environment, expected) => {
  expect(formatPageTitle("Review Queue", createPageTitleConfig({ VITE_DEPLOYMENT_ENV: environment }))).toBe(expected);
});

it("has safe defaults and a single configurable application name", () => {
  const config = createPageTitleConfig({ VITE_APPLICATION_NAME: "  Institutional AI  ", VITE_DEPLOYMENT_ENV: "prod" });
  expect(formatPageTitle(undefined, config)).toBe("Workspace | Institutional AI");
  expect(formatPageTitle("", config)).toBe("Workspace | Institutional AI");
  expect(formatPageTitle("Document Upload", config)).toBe("Document Upload | Institutional AI");
  expect(fallbackTitleHtml(config)).toBe("<title>Institutional AI</title>");
  expect(createPageTitleConfig({ VITE_APPLICATION_NAME: " " }).applicationName).toBe("Document AI");
});

it("escapes configurable text in the HTML fallback", () => {
  expect(
    fallbackTitleHtml(createPageTitleConfig({ VITE_APPLICATION_NAME: "R&D </title><script>alert(1)</script>" })),
  ).toBe("<title>R&amp;D &lt;/title&gt;&lt;script&gt;alert(1)&lt;/script&gt;</title>");
});
