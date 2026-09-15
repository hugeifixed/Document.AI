import { matchRoutes, type RouteObject } from "react-router-dom";
import { pageRoutes, signInRoute } from "./page-routes";
import { createPageTitleConfig, formatPageTitle } from "./page-title-config";

const expected = [
  ["/", "Workspace"],
  ["/projects", "Projects"],
  ["/datasets", "Document Upload"],
  ["/documents/private-record", "Extraction Results"],
  ["/workflows/new", "New Workflow"],
  ["/configurations", "Workflows"],
  ["/runs", "Processing History"],
  ["/runs/private-record", "Processing Run"],
  ["/results", "Extraction Results"],
  ["/review", "Review Queue"],
  ["/review/private-record", "Document Review"],
  ["/labeling", "Ground Truth"],
  ["/labeling/private-record", "Document Labeling"],
  ["/metrics", "Metrics"],
  ["/evaluation", "Evaluation"],
  ["/exports", "Exports"],
  ["/settings", "Settings"],
  ["/unknown-private-record", "Page Not Found"],
  ["/login", "Sign In"],
];
const routes: RouteObject[] = [signInRoute, { path: "/", children: [...pageRoutes] }];

it("inventories every registered page", () => {
  expect(pageRoutes.length + 1).toBe(expected.length);
  expect(new Set(pageRoutes.map((route) => route.id)).size).toBe(pageRoutes.length);
});

it.each(expected)("%s has its approved static label", (path, label) => {
  const matched = matchRoutes(routes, `${path}?customer=private-customer&account=123456#private-text`);
  const handle = matched?.at(-1)?.route.handle;
  expect(handle?.pageTitle).toBe(label);
  const title = formatPageTitle(
    handle?.pageTitle,
    createPageTitleConfig({ VITE_APPLICATION_NAME: "Renamed AI", VITE_DEPLOYMENT_ENV: "prod" }),
  );
  expect(title).toBe(`${label} | Renamed AI`);
  expect(title).not.toMatch(/undefined|null|private|123456/);
});
