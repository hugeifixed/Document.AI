import type { ReactNode } from "react";
import { ParentSize } from "@visx/responsive";
import { Card } from "@/common/components/ui/card/card";
import { ScrollRegion } from "@/common/components/ui/scroll-region/scroll-region";
import { type ChartProps, chartValue } from "../chart-types";
export function ChartFrame({
  title,
  description,
  rows,
  series,
  unit,
  children,
  onPointerLeave,
}: ChartProps & { children: (width: number) => ReactNode; onPointerLeave?: () => void }) {
  const empty = !rows.some((row) => row.values.some((value) => value != null && value > 0));
  return (
    <Card title={title}>
      <p className="mb-3 text-caption text-secondary">{description}</p>
      <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-caption" aria-label={`${title} legend`}>
        {series.map((item, index) => (
          <li key={item.label} className="flex items-center gap-2">
            <svg width="24" height="12" aria-hidden="true">
              <line
                x1="0"
                y1="6"
                x2="24"
                y2="6"
                stroke={item.color}
                strokeWidth="3"
                strokeDasharray={index ? `${index * 2} 3` : undefined}
              />
            </svg>
            {item.label}
          </li>
        ))}
      </ul>
      <div className="relative h-72 min-w-0" onPointerLeave={onPointerLeave}>
        {empty ? (
          <p className="flex h-full items-center justify-center text-center text-secondary">
            No recorded values for these filters.
          </p>
        ) : (
          <ParentSize debounceTime={0}>{({ width }) => children(Math.max(width, 1))}</ParentSize>
        )}
      </div>
      <details className="collapse collapse-arrow mt-3 border border-base-300 bg-base-100">
        <summary className="collapse-title min-h-11 py-3 text-sm font-medium">
          Show data table<span className="sr-only">: {title}</span>
        </summary>
        <div className="collapse-content">
          <ScrollRegion label={`${title} data`}>
            <table className="table table-sm tabular-nums">
              <caption className="sr-only">
                {title}
                {unit ? ` (${unit})` : ""}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Date / category</th>
                  {series.map((item) => (
                    <th key={item.label} scope="col">
                      {item.label}
                      {unit ? ` (${unit})` : ""}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.label}>
                    <th scope="row" className="font-normal">
                      {row.label}
                    </th>
                    {row.values.map((value, index) => (
                      <td key={series[index].label}>{chartValue(value, unit)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        </div>
      </details>
    </Card>
  );
}
