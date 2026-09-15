import { AxisBottom, AxisLeft } from "@visx/axis";
import { scaleLinear, scalePoint } from "@visx/scale";
import { LinePath } from "@visx/shape";
import { useChartTooltip } from "../../hooks/use-chart-tooltip";
import { useId } from "react";
import { ChartInspection } from "../chart-inspection/chart-inspection";
import { ChartFrame } from "../chart-frame/chart-frame";
import type { ChartProps } from "../../types/chart-types";
export function LineChart(props: ChartProps) {
  const tooltip = useChartTooltip(props.rows);
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
                            tooltipData: row.label,
                            tooltipLeft: x(row.label),
                            tooltipTop: y(row.values[index] ?? 0),
                          })
                        }
                        onPointerDown={() =>
                          tooltip.showTooltip({
                            tooltipData: row.label,
                            tooltipLeft: x(row.label),
                            tooltipTop: y(row.values[index] ?? 0),
                          })
                        }
                      />
                    ))}
                </g>
              ))}
            </svg>
            <ChartInspection {...props} tooltip={tooltip} id={id} width={width} />
          </>
        );
      }}
    </ChartFrame>
  );
}
