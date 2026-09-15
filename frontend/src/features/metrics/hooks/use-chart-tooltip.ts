import { type FocusEvent, useEffect, useRef } from "react";
import { useTooltip } from "@visx/tooltip";
import type { ChartRow } from "../types/chart-types";
export function useChartTooltip(rows: ChartRow[]) {
  const inspectionRef = useRef<HTMLSelectElement>(null);
  const tooltip = useTooltip<string>();
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
    if (inspectionRef.current?.contains(document.activeElement)) return;
    hideTooltip();
  }
  function hideAfterInspectionBlur(event: FocusEvent<HTMLSelectElement>) {
    // Customizable native selects focus their options; their blur bubbles here
    // before focus returns to the select after a keyboard selection.
    if (event.currentTarget.contains(event.relatedTarget)) return;
    hideTooltip();
  }
  const inspectedRow = rows.find((row) => row.label === tooltip.tooltipData);
  return { ...tooltip, inspectedRow, inspectionRef, hidePointerTooltip, hideAfterInspectionBlur };
}
