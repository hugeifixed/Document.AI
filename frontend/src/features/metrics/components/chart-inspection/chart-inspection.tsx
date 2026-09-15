import { TooltipWithBounds } from "@visx/tooltip";
import { SelectControl } from "@/common/components/ui/select-control/select-control";
import type { useChartTooltip } from "../../hooks/use-chart-tooltip";
import type { ChartProps } from "../../types/chart-types";
import { chartValue } from "../../utils/chart-values";
export function ChartInspection({
  title,
  rows,
  series,
  unit,
  tooltip: {
    inspectedRow: row,
    tooltipOpen,
    inspectionRef,
    showTooltip,
    hideTooltip,
    hideAfterInspectionBlur,
    tooltipTop,
    tooltipLeft,
  },
  id,
  width,
}: ChartProps & {
  tooltip: ReturnType<typeof useChartTooltip>;
  id: string;
  width: number;
}) {
  const open = tooltipOpen && !!row;
  return (
    <>
      <div className="absolute inset-x-0 bottom-0 flex justify-center">
        <SelectControl
          ref={inspectionRef}
          className="min-h-11 w-56 max-w-full"
          aria-label={`Inspect ${title}`}
          aria-describedby={open ? `${id}-tooltip` : undefined}
          value={row?.label ?? ""}
          onChange={(event) => {
            if (event.target.value)
              showTooltip({ tooltipData: event.target.value, tooltipLeft: width / 2, tooltipTop: 50 });
            else hideTooltip();
          }}
          onBlur={hideAfterInspectionBlur}
          onKeyDown={(event) => {
            if (event.key === "Escape") hideTooltip();
          }}
        >
          <option value="">Inspect a data point</option>
          {rows.map((item) => (
            <option key={item.label}>{item.label}</option>
          ))}
        </SelectControl>
      </div>
      {open && (
        <TooltipWithBounds
          top={tooltipTop}
          left={tooltipLeft}
          unstyled
          className="absolute z-10 rounded-box border border-base-300 bg-base-100 p-4 text-caption text-base-content elevation-overlay sm:p-5"
          role="tooltip"
          id={`${id}-tooltip`}
        >
          <strong>{row.label}</strong>
          {series.map((item, index) => (
            <p key={item.label}>
              {item.label}: {chartValue(row.values[index], unit)}
            </p>
          ))}
        </TooltipWithBounds>
      )}
    </>
  );
}
