// Page labels are static so even an unresolved lazy module has a safe title.
export const signInRoute = { path: "/login", handle: { pageTitle: "Sign In" } };

export const pageRoutes = [
  { id: "workspace", index: true, handle: { pageTitle: "Workspace" } },
  { id: "projects", path: "projects", handle: { pageTitle: "Projects" } },
  { id: "datasets", path: "datasets", handle: { pageTitle: "Document Upload" } },
  { id: "document", path: "documents/:documentId", handle: { pageTitle: "Extraction Results" } },
  { id: "workflow", path: "workflows/new", handle: { pageTitle: "New Workflow" } },
  { id: "configurations", path: "configurations", handle: { pageTitle: "Workflows" } },
  { id: "runs", path: "runs", handle: { pageTitle: "Processing History" } },
  { id: "run", path: "runs/:id", handle: { pageTitle: "Processing Run" } },
  { id: "results", path: "results", handle: { pageTitle: "Extraction Results" } },
  { id: "review", path: "review", handle: { pageTitle: "Review Queue" } },
  { id: "document-review", path: "review/:documentId", handle: { pageTitle: "Document Review" } },
  { id: "labeling", path: "labeling", handle: { pageTitle: "Ground Truth" } },
  { id: "document-labeling", path: "labeling/:documentId", handle: { pageTitle: "Document Labeling" } },
  { id: "evaluation", path: "evaluation", handle: { pageTitle: "Evaluation" } },
  { id: "exports", path: "exports", handle: { pageTitle: "Exports" } },
  { id: "settings", path: "settings", handle: { pageTitle: "Settings" } },
  { id: "not-found", path: "*", handle: { pageTitle: "Page Not Found" } },
] as const;
