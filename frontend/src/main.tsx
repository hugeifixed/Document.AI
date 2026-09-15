import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Outlet, RouterProvider } from "react-router-dom";
import "./app.css";
import { pageRoutes, signInRoute } from "./app/page-routes";
import { PageTitleOwner } from "./app/page-title-owner/page-title-owner";
import { ApiError, isAuthenticationError } from "./common/api/client";
import { RequireSession, SessionProvider, useSession } from "./auth/Session";
import { useWorkingContext } from "./workspace/context";
import { RouteError } from "./components/RouteError";

// A deployment can replace hashed route chunks while a user still has the old
// application shell open. Reload once to pick up the new index; if the new
// deployment is itself broken, let the route error boundary handle the repeat
// failure instead of creating a reload loop.
const PRELOAD_RECOVERY_KEY = "docai:vite-preload-recovery";
const PRELOAD_RECOVERY_WINDOW_MS = 60_000;
window.addEventListener("vite:preloadError", (event) => {
  const now = Date.now();
  try {
    const previous = Number(sessionStorage.getItem(PRELOAD_RECOVERY_KEY));
    if (previous > 0 && now - previous >= 0 && now - previous < PRELOAD_RECOVERY_WINDOW_MS) return;
    sessionStorage.setItem(PRELOAD_RECOVERY_KEY, String(now));
  } catch {
    // Storage can be unavailable in locked-down browsers. The rejected route
    // import will continue to the existing error boundary in that case.
    return;
  }
  event.preventDefault();
  window.location.reload();
});

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) =>
        !isAuthenticationError(error) &&
        !(error instanceof ApiError && error.status >= 400 && error.status < 500) &&
        count < 1,
      staleTime: 10000,
      refetchOnWindowFocus: false,
    },
  },
});

const pageModules = {
  workspace: async () => ({ Component: (await import("./pages/Dashboard")).Dashboard }),
  projects: async () => ({ Component: (await import("./pages/Projects")).Projects }),
  datasets: async () => ({ Component: (await import("./pages/Datasets")).Datasets }),
  document: async () => ({ Component: (await import("./pages/ReviewWorkspace")).DocumentPage }),
  workflow: async () => ({ Component: (await import("./pages/WorkflowBuilder")).WorkflowBuilder }),
  configurations: async () => ({ Component: (await import("./pages/Configurations")).Configurations }),
  runs: async () => ({ Component: (await import("./pages/Runs")).Runs }),
  run: async () => ({ Component: (await import("./pages/RunDetail")).RunDetail }),
  results: async () => ({ Component: (await import("./pages/Results")).Results }),
  review: async () => ({ Component: (await import("./pages/ReviewQueue")).ReviewQueue }),
  "document-review": async () => ({ Component: (await import("./pages/ReviewWorkspace")).ReviewPage }),
  labeling: async () => ({ Component: (await import("./pages/Labeling")).Labeling }),
  "document-labeling": async () => ({ Component: (await import("./pages/ReviewWorkspace")).LabelPage }),
  metrics: async () => {
    const { MetricsRoute } = await import("./app/routes/metrics-route");
    return {
      Component: function MetricsPage() {
        const { projectId, datasetId } = useWorkingContext();
        const { user } = useSession();
        return (
          <MetricsRoute
            projectId={projectId}
            datasetId={datasetId}
            canViewUsage={!!user?.roles.includes("docai_operators")}
          />
        );
      },
    };
  },
  evaluation: async () => ({ Component: (await import("./pages/Evaluation")).EvaluationPage }),
  exports: async () => ({ Component: (await import("./pages/Exports")).Exports }),
  settings: async () => ({ Component: (await import("./pages/Settings")).Settings }),
  "not-found": async () => ({ Component: (await import("./pages/NotFound")).NotFound }),
};

const router = createBrowserRouter([
  {
    element: <SessionProvider />,
    errorElement: <RouteError />,
    children: [
      {
        ...signInRoute,
        lazy: async () => ({ Component: (await import("./pages/Login")).Login }),
      },
      {
        element: <RequireSession />,
        children: [
          {
            path: "/",
            lazy: async () => ({ Component: (await import("./layouts/AppShell")).AppShell }),
            children: [
              {
                element: <Outlet />,
                errorElement: <RouteError />,
                children: pageRoutes.map((route) => ({ ...route, lazy: pageModules[route.id] })),
              },
            ],
          },
        ],
      },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <PageTitleOwner router={router}>
        <RouterProvider router={router} />
      </PageTitleOwner>
    </QueryClientProvider>
  </StrictMode>,
);
