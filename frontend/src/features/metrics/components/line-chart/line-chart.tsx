import { AxisBottom, AxisLeft } from "@visx/axis";
import { scaleLinear, scalePoint } from "@visx/scale";
import { LinePath } from "@visx/shape";
import { TooltipWithBounds } from "@visx/tooltip";
import { useChartTooltip } from "../use-chart-tooltip";
import { useId } from "react";
import { SelectControl } from "@/common/components/ui/select-control/select-control";
import { ChartFrame } from "../chart-frame/chart-frame";
import { type ChartProps, chartValue } from "../chart-types";
export function LineChart(props: ChartProps) {
  const tooltip = useChartTooltip();
  const id = useId();
  return (
    <ChartFrame {...props} onPointerLeave={tooltip.hidePointerTooltip}>
      {(width) => {
        const x = scalePoint({
          domain: props.rows.map((r) => r.label),
          range: [52, Math.max(53, width - 16)],
          padding: 0.5,
        });
        const y = scaleLinear({
          domain: [0, Math.max(1, ...props.rows.flatMap((r) => r.values.map((v) => v ?? 0)))],
          range: [212, 12],
          nice: true,
        });
        const ticks = props.rows
          .filter((_, i) => i % Math.max(1, Math.ceil(props.rows.length / 4)) === 0)
          .map((r) => r.label);
        return (
          <>
            <svg width={width} height={256} aria-labelledby={id}>
              <title id={id}>
                {props.title}. {props.description} Exact values available in the data table.
              </title>
              <AxisBottom
                top={212}
                scale={x}
                tickValues={ticks}
                tickFormat={(v) => String(v).slice(5)}
                stroke="var(--color-secondary)"
                tickStroke="var(--color-secondary)"
                tickLabelProps={{ fill: "var(--color-secondary)", fontSize: 11, textAnchor: "middle" }}
              />
              <AxisLeft
                left={52}
                scale={y}
                numTicks={4}
                stroke="var(--color-secondary)"
                tickStroke="var(--color-secondary)"
                tickLabelProps={{ fill: "var(--color-secondary)", fontSize: 11, textAnchor: "end", dx: -4 }}
              />
              {props.series.map((series, index) => (
                <g key={series.label}>
                  <LinePath
                    data={props.rows}
                    defined={(r) => r.values[index] != null}
                    x={(r) => x(r.label) ?? 0}
                    y={(r) => y(r.values[index] ?? 0)}
                    stroke={series.color}
                    strokeWidth={2}
                    strokeDasharray={index ? "6 4" : undefined}
                  />
                  {props.rows
                    .filter((r) => r.values[index] != null)
                    .map((row) => (
                      <circle
                        key={row.label}
                        cx={x(row.label)}
                        cy={y(row.values[index] ?? 0)}
                        r={3}
                        fill={series.color}
                        onPointerMove={() =>
                          tooltip.showTooltip({
                            tooltipData: row,
                            tooltipLeft: x(row.label),
                            tooltipTop: y(row.values[index] ?? 0),
                          })
                        }
                        onPointerDown={() =>
                          tooltip.showTooltip({
                            tooltipData: row,
                            tooltipLeft: x(row.label),
                            tooltipTop: y(row.values[index] ?? 0),
                          })
                        }
                      />
                    ))}
                </g>
              ))}
            </svg>
            <div
              className="absolute inset-x-0 bottom-0 flex justify-center gap-1"
              aria-label={`${props.title} data points`}
            >
              <SelectControl
                ref={tooltip.inspectionRef}
                className="min-h-11 w-56 max-w-full"
                aria-label={`Inspect ${props.title}`}
                aria-describedby={tooltip.tooltipOpen ? `${id}-tooltip` : undefined}
                defaultValue=""
                onChange={(e) => {
                  const row = props.rows.find((r) => r.label === e.target.value);
                  if (row) tooltip.showTooltip({ tooltipData: row, tooltipLeft: width / 2, tooltipTop: 50 });
                  else tooltip.hideTooltip();
                }}
                onBlur={tooltip.hideTooltip}
                onKeyDown={(e) => {
                  if (e.key === "Escape") tooltip.hideTooltip();
                }}
              >
                <option value="">Inspect a date</option>
                {props.rows.map((row) => (
                  <option key={row.label}>{row.label}</option>
                ))}
              </SelectControl>
            </div>
            {tooltip.tooltipOpen && tooltip.tooltipData && (
              <TooltipWithBounds
                top={tooltip.tooltipTop}
                left={tooltip.tooltipLeft}
                unstyled
                className="absolute z-10 rounded-box border border-base-300 bg-base-100 p-3 text-caption text-base-content elevation-overlay"
                role="tooltip"
                id={`${id}-tooltip`}
              >
                <strong>{tooltip.tooltipData.label}</strong>
                {props.series.map((series, index) => (
                  <p key={series.label}>
                    {series.label}: {chartValue(tooltip.tooltipData!.values[index], props.unit)}
                  </p>
                ))}
              </TooltipWithBounds>
            )}
          </>
        );
      }}
    </ChartFrame>
  );
}
