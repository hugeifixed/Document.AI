import { AxisBottom, AxisLeft } from "@visx/axis";
import { scaleBand, scaleLinear } from "@visx/scale";
import { Bar } from "@visx/shape";
import { useChartTooltip } from "../../hooks/use-chart-tooltip";
import { useId } from "react";
import { ChartInspection } from "../chart-inspection/chart-inspection";
import { ChartFrame } from "../chart-frame/chart-frame";
import type { ChartProps } from "../../types/chart-types";
export function BarChart(props: ChartProps) {
  const id = useId().replaceAll(":", "");
  const tooltip = useChartTooltip(props.rows);
  return (
    <ChartFrame {...props} onPointerLeave={tooltip.hidePointerTooltip}>
      {(width) => {
        const x = scaleBand({
          domain: props.rows.map((r) => r.label),
          range: [52, Math.max(53, width - 16)],
          padding: 0.25,
        });
        const y = scaleLinear({
          domain: [0, Math.max(1, ...props.rows.map((r) => r.values.reduce<number>((sum, v) => sum + (v ?? 0), 0)))],
          range: [208, 12],
          nice: true,
        });
        const ticks = props.rows
          .filter((_, i) => i % Math.max(1, Math.ceil(props.rows.length / 4)) === 0)
          .map((r) => r.label);
        return (
          <>
            <svg width={width} height={256} aria-labelledby={`${id}-title`}>
              <title id={`${id}-title`}>
                {props.title}. {props.description} Exact values available in the data table.
              </title>
              <defs>
                {props.series.map((series, i) => (
                  <pattern
                    key={series.label}
                    id={`${id}-${i}`}
                    width={4 + i * 2}
                    height={4 + i * 2}
                    patternUnits="userSpaceOnUse"
                    patternTransform={`rotate(${i % 2 ? 45 : -45})`}
                  >
                    <rect width="100%" height="100%" fill={series.color} />
                    {i > 0 && <line x1="0" y1="0" x2="0" y2="10" stroke="var(--color-base-100)" strokeWidth="2" />}
                  </pattern>
                ))}
              </defs>
              <AxisBottom
                top={208}
                scale={x}
                tickValues={ticks}
                tickFormat={(value) =>
                  /^\d{4}-/.test(String(value)) ? String(value).slice(5) : String(value).slice(0, 10)
                }
                stroke="var(--color-secondary)"
                tickStroke="var(--color-secondary)"
                tickLabelProps={{ fill: "var(--color-secondary)", fontSize: 10, textAnchor: "middle" }}
              />
              <AxisLeft
                left={52}
                scale={y}
                numTicks={4}
                stroke="var(--color-secondary)"
                tickStroke="var(--color-secondary)"
                tickLabelProps={{ fill: "var(--color-secondary)", fontSize: 11, textAnchor: "end", dx: -4 }}
              />
              {props.rows.map((row) => {
                let sum = 0;
                return (
                  <g key={row.label}>
                    {row.values.map((value, index) => {
                      const base = sum;
                      sum += value ?? 0;
                      return (
                        <Bar
                          key={props.series[index].label}
                          x={x(row.label)}
                          y={y(sum)}
                          width={x.bandwidth()}
                          height={y(base) - y(sum)}
                          fill={`url(#${id}-${index})`}
                          onPointerMove={() =>
                            tooltip.showTooltip({
                              tooltipData: row.label,
                              tooltipLeft: x(row.label),
                              tooltipTop: y(sum),
                            })
                          }
                          onPointerDown={() =>
                            tooltip.showTooltip({
                              tooltipData: row.label,
                              tooltipLeft: x(row.label),
                              tooltipTop: y(sum),
                            })
                          }
                        />
                      );
                    })}
                  </g>
                );
              })}
            </svg>
            <ChartInspection {...props} tooltip={tooltip} id={id} width={width} />
          </>
        );
      }}
    </ChartFrame>
  );
}
