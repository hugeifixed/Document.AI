import { useEffect, useRef } from "react";
import { useTooltip } from "@visx/tooltip";
import type { ChartRow } from "./chart-types";
export function useChartTooltip() {
  const inspectionRef = useRef<HTMLSelectElement>(null);
  const tooltip = useTooltip<ChartRow>();
  const { tooltipOpen, hideTooltip } = tooltip;
  useEffect(() => {
    if (!tooltipOpen) return;
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === "Escape") hideTooltip();
    };
    document.addEventListener("keydown", dismiss);
    return () => document.removeEventListener("keydown", dismiss);
  }, [tooltipOpen, hideTooltip]);
  function hidePointerTooltip() {
    // Native select menus can emit pointer-leave while keyboard focus stays here.
    if (inspectionRef.current === document.activeElement) return;
    hideTooltip();
  }
  return { ...tooltip, inspectionRef, hidePointerTooltip };
}
