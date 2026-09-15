import { createContext, useContext, useLayoutEffect } from "react";

export const PageTitleStateContext = createContext<{
  locationKey: string;
  report: (locationKey: string, label: string) => () => void;
} | null>(null);

/** Declare a rendered page state; only PageTitleOwner writes document.title. */
export function usePageTitleState(label: string | undefined) {
  const context = useContext(PageTitleStateContext);
  const locationKey = context?.locationKey;
  const report = context?.report;
  useLayoutEffect(() => {
    if (label && locationKey && report) return report(locationKey, label);
  }, [label, locationKey, report]);
}
