import { useEffect } from "react";
import { useTooltip } from "@visx/tooltip";
import type { ChartRow } from "./chart-types";
export function useChartTooltip() {
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
  return tooltip;
}
