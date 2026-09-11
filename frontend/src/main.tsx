import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Outlet, RouterProvider } from "react-router-dom";
import "./app.css";
import { ApiError, isAuthenticationError } from "./api/client";
import { RequireSession, SessionProvider } from "./auth/Session";
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

const router = createBrowserRouter([
  {
    element: <SessionProvider />,
    errorElement: <RouteError />,
    children: [
      {
        path: "/login",
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
                children: [
                  { index: true, lazy: async () => ({ Component: (await import("./pages/Dashboard")).Dashboard }) },
                  { path: "projects", lazy: async () => ({ Component: (await import("./pages/Projects")).Projects }) },
                  { path: "datasets", lazy: async () => ({ Component: (await import("./pages/Datasets")).Datasets }) },
                  {
                    path: "documents/:documentId",
                    lazy: async () => ({ Component: (await import("./pages/ReviewWorkspace")).DocumentPage }),
                  },
                  {
                    path: "workflows/new",
                    lazy: async () => ({ Component: (await import("./pages/WorkflowBuilder")).WorkflowBuilder }),
                  },
                  {
                    path: "configurations",
                    lazy: async () => ({ Component: (await import("./pages/Configurations")).Configurations }),
                  },
                  { path: "runs", lazy: async () => ({ Component: (await import("./pages/Runs")).Runs }) },
                  {
                    path: "runs/:id",
                    lazy: async () => ({ Component: (await import("./pages/RunDetail")).RunDetail }),
                  },
                  { path: "results", lazy: async () => ({ Component: (await import("./pages/Results")).Results }) },
                  {
                    path: "review",
                    lazy: async () => ({ Component: (await import("./pages/ReviewQueue")).ReviewQueue }),
                  },
                  {
                    path: "review/:documentId",
                    lazy: async () => ({ Component: (await import("./pages/ReviewWorkspace")).ReviewPage }),
                  },
                  { path: "labeling", lazy: async () => ({ Component: (await import("./pages/Labeling")).Labeling }) },
                  {
                    path: "labeling/:documentId",
                    lazy: async () => ({ Component: (await import("./pages/ReviewWorkspace")).LabelPage }),
                  },
                  {
                    path: "evaluation",
                    lazy: async () => ({ Component: (await import("./pages/Evaluation")).EvaluationPage }),
                  },
                  { path: "exports", lazy: async () => ({ Component: (await import("./pages/Exports")).Exports }) },
                  { path: "settings", lazy: async () => ({ Component: (await import("./pages/Settings")).Settings }) },
                  { path: "*", lazy: async () => ({ Component: (await import("./pages/NotFound")).NotFound }) },
                ],
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
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
