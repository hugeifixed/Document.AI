import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Outlet, RouterProvider } from "react-router-dom";
import "./app.css";
import { ApiError, isAuthenticationError } from "./api/client";
import { RequireSession, SessionProvider } from "./auth/Session";
import { RouteError } from "./components/RouteError";

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
