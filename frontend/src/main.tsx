import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import "./app.css";
import { ApiError, isAuthenticationError } from "./api/client";
import { RequireSession, SessionProvider } from "./auth/Session";
import { AppShell } from "./layouts/AppShell";
import { Configurations } from "./pages/Configurations";
import { Dashboard } from "./pages/Dashboard";
import { Datasets } from "./pages/Datasets";
import { EvaluationPage } from "./pages/Evaluation";
import { Exports } from "./pages/Exports";
import { Labeling } from "./pages/Labeling";
import { Login } from "./pages/Login";
import { NotFound } from "./pages/NotFound";
import { Projects } from "./pages/Projects";
import { Results } from "./pages/Results";
import { ReviewQueue } from "./pages/ReviewQueue";
import { ReviewWorkspace } from "./pages/ReviewWorkspace";
import { RunDetail } from "./pages/RunDetail";
import { Runs } from "./pages/Runs";
import { Settings } from "./pages/Settings";
import { WorkflowBuilder } from "./pages/WorkflowBuilder";

const qc = new QueryClient({ defaultOptions: { queries: {
  retry: (count, error) => !isAuthenticationError(error) && !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 1,
  staleTime: 10000, refetchOnWindowFocus: false,
} } });
const router = createBrowserRouter([{ element: <SessionProvider />, children: [
  { path: "/login", element: <Login /> },
  { element: <RequireSession />, children: [{
  path: "/", element: <AppShell />, children: [
    { index: true, element: <Dashboard /> }, { path: "projects", element: <Projects /> }, { path: "datasets", element: <Datasets /> },
    { path: "workflows/new", element: <WorkflowBuilder /> }, { path: "configurations", element: <Configurations /> },
    { path: "runs", element: <Runs /> }, { path: "runs/:id", element: <RunDetail /> }, { path: "results", element: <Results /> },
    { path: "review", element: <ReviewQueue /> }, { path: "review/:documentId", element: <ReviewWorkspace mode="review" /> },
    { path: "labeling", element: <Labeling /> }, { path: "labeling/:documentId", element: <ReviewWorkspace mode="label" /> },
    { path: "evaluation", element: <EvaluationPage /> }, { path: "exports", element: <Exports /> }, { path: "settings", element: <Settings /> },
    { path: "*", element: <NotFound /> },
  ],
  }] },
] }]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
