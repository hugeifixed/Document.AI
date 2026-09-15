import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { createMemoryRouter, Outlet, type RouteObject, RouterProvider } from "react-router-dom";
import { RouteError } from "@/components/RouteError";
import { NotFound } from "@/pages/NotFound";
import { pageRoutes, signInRoute } from "../page-routes";
import { createPageTitleConfig } from "../page-title-config";
import { usePageTitleState } from "@/common/hooks/use-page-title-state";
import { PageTitleOwner } from "./page-title-owner";

const routers: ReturnType<typeof createMemoryRouter>[] = [];
afterEach(() => {
  cleanup();
  routers.splice(0).forEach((router) => router.dispose());
  vi.restoreAllMocks();
});

function setup(children: RouteObject[], path = "/review") {
  const router = createMemoryRouter([{ element: <Outlet />, errorElement: <RouteError />, children }], {
    initialEntries: [path],
  });
  routers.push(router);
  render(
    <StrictMode>
      <PageTitleOwner router={router} config={createPageTitleConfig({ VITE_DEPLOYMENT_ENV: "prod" })}>
        <RouterProvider router={router} />
      </PageTitleOwner>
    </StrictMode>,
  );
  return router;
}

const reviewRoute = pageRoutes.find(({ id }) => id === "review")!;
const resultsRoute = pageRoutes.find(({ id }) => id === "results")!;
const notFoundRoute = pageRoutes.find(({ id }) => id === "not-found")!;

it("updates on navigation, Back and Forward, including the real unknown page", async () => {
  const router = setup([
    { ...reviewRoute, element: <p>Empty review queue</p> },
    { ...resultsRoute, element: <p>Results failed to load</p> },
    { ...notFoundRoute, element: <NotFound /> },
    { ...signInRoute, element: <p>Sign in</p> },
  ]);
  expect(document.title).toBe("Review Queue | Document AI");
  await act(() => router.navigate("/results?customer=private-name"));
  expect(document.title).toBe("Extraction Results | Document AI");
  await act(() => router.navigate(-1));
  expect(document.title).toBe("Review Queue | Document AI");
  await act(() => router.navigate(1));
  expect(document.title).toBe("Extraction Results | Document AI");
  await act(() => router.navigate("/unknown-private-file"));
  expect(document.title).toBe("Page Not Found | Document AI");
  await act(() => router.navigate("/login?next=private"));
  expect(document.title).toBe("Sign In | Document AI");
  await act(() => router.navigate("/review"));
  expect(document.title).toBe("Review Queue | Document AI");
});

it.each(["direct entry", "navigation"])(
  "sets a title before a lazy route and its loader resolve on %s",
  async (entry) => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const router = setup(
      [
        { ...reviewRoute, element: <p>Review</p> },
        {
          ...resultsRoute,
          lazy: async () => {
            await gate;
            return { Component: () => <p>Empty results</p> };
          },
          loader: () => gate,
        },
      ],
      entry === "direct entry" ? "/results?filename=private.txt" : "/review",
    );
    let navigation: Promise<void> | undefined;
    if (entry === "navigation")
      act(() => {
        navigation = router.navigate("/results?filename=private.txt");
      });
    await waitFor(() => expect(document.title).toBe("Extraction Results | Document AI"));
    expect(screen.queryByText("Empty results")).not.toBeInTheDocument();
    await act(async () => {
      release();
      await navigation;
    });
    await screen.findByText("Empty results");
    expect(document.title).toBe("Extraction Results | Document AI");
  },
);

it.each([
  [403, "Access Denied"],
  [404, "Page Not Found"],
  [500, "Page Error"],
])("uses the error title for a %s router failure and recovers on navigation", async (status, label) => {
  const router = setup([
    {
      ...reviewRoute,
      loader: () => {
        throw new Response("private details", { status });
      },
      element: <p>Review</p>,
    },
    { ...resultsRoute, element: <p>Results</p> },
  ]);
  await screen.findByRole("heading", { name: "Something went wrong" });
  expect(document.title).toBe(`${label} | Document AI`);
  await act(() => router.navigate("/results"));
  expect(document.title).toBe("Extraction Results | Document AI");
});

it("lets the actual render-error boundary declare its title through the same owner", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  function BrokenPage(): never {
    throw new Error("private record content");
  }
  const router = setup([
    { ...reviewRoute, element: <BrokenPage /> },
    { ...resultsRoute, element: <p>Results</p> },
  ]);
  await screen.findByRole("heading", { name: "Something went wrong" });
  expect(document.title).toBe("Page Error | Document AI");
  await act(() => router.navigate("/results"));
  expect(document.title).toBe("Extraction Results | Document AI");
});

it("clears a declared denied state when the state changes or its route unmounts", async () => {
  let denied = true;
  function PageState() {
    usePageTitleState(denied ? "Access Denied" : undefined);
    return <p>{denied ? "Denied" : "Allowed"}</p>;
  }
  const router = setup([
    { ...reviewRoute, element: <PageState /> },
    { ...resultsRoute, element: <p>Results</p> },
  ]);
  expect(document.title).toBe("Access Denied | Document AI");
  denied = false;
  await act(() => router.navigate("/review?retry=1"));
  expect(document.title).toBe("Review Queue | Document AI");
  denied = true;
  await act(() => router.navigate("/review?retry=2"));
  expect(document.title).toBe("Access Denied | Document AI");
  await act(() => router.navigate("/results"));
  expect(document.title).toBe("Extraction Results | Document AI");
});

it("uses a nonempty fallback when no matched route declares a label", () => {
  setup([{ path: "*", element: <p>Application</p> }]);
  expect(document.title).toBe("Workspace | Document AI");
});
