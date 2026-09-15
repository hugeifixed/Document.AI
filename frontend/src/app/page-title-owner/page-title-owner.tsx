import { type ReactNode, useCallback, useLayoutEffect, useMemo, useState, useSyncExternalStore } from "react";
import { type createBrowserRouter, matchRoutes } from "react-router-dom";
import { errorPageTitle } from "@/common/utils/error-page-title";
import { PageTitleStateContext } from "@/common/hooks/use-page-title-state";
import { createPageTitleConfig, formatPageTitle, type PageTitleConfig } from "../page-title-config";

type Router = ReturnType<typeof createBrowserRouter>;
const deploymentConfig = createPageTitleConfig({
  VITE_APPLICATION_NAME: import.meta.env.VITE_APPLICATION_NAME,
  VITE_DEPLOYMENT_ENV: import.meta.env.VITE_DEPLOYMENT_ENV,
});

/** Mounted outside RouterProvider: lazy routes, session checks and boundaries cannot hide the owner. */
export function PageTitleOwner({
  router,
  children,
  config = deploymentConfig,
}: {
  router: Router;
  children: ReactNode;
  config?: PageTitleConfig;
}) {
  const subscribe = useCallback((notify: () => void) => router.subscribe(notify), [router]);
  const state = useSyncExternalStore(subscribe, () => router.state);
  const [pageState, setPageState] = useState<{ key: string; label: string; token: symbol }>();
  const report = useCallback((key: string, label: string) => {
    const token = Symbol();
    setPageState({ key, label, token });
    return () => setPageState((current) => (current?.token === token ? undefined : current));
  }, []);
  const context = useMemo(() => ({ locationKey: state.location.key, report }), [state.location.key, report]);
  const destination = state.navigation.location;
  const matches = matchRoutes(router.routes, destination ?? state.location);
  const routeLabel = matches
    ?.map(({ route }) => route.handle?.pageTitle as string | undefined)
    .filter(Boolean)
    .at(-1);
  const errors = !destination && state.errors ? Object.values(state.errors) : [];
  const label = errors.length
    ? errorPageTitle(errors[0])
    : !destination && pageState?.key === state.location.key
      ? pageState.label
      : routeLabel;
  const title = formatPageTitle(label, config);
  useLayoutEffect(() => {
    document.title = title;
  }, [title]);

  return <PageTitleStateContext.Provider value={context}>{children}</PageTitleStateContext.Provider>;
}
