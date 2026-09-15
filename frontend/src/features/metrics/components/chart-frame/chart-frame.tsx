import type { ReactNode } from "react";
import { ParentSize } from "@visx/responsive";
import { Card } from "@/common/components/ui/card/card";
import { ScrollRegion } from "@/common/components/ui/scroll-region/scroll-region";
import type { ChartProps } from "../../types/chart-types";
import { chartValue } from "../../utils/chart-values";
export function ChartFrame({
  title,
  description,
  rows,
  series,
  unit,
  children,
  onPointerLeave,
}: ChartProps & { children: (width: number) => ReactNode; onPointerLeave?: () => void }) {
  const empty = !rows.some((row) => row.values.some((value) => value != null));
  return (
    <Card title={title} flush className="shadow-none!">
      <div className="px-4 sm:px-5">
        <p className="mb-4 text-caption text-secondary">{description}</p>
        <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-2 text-caption" aria-label={`${title} legend`}>
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
              No recorded values for these filters. Choose another date range or refresh after activity is recorded.
            </p>
          ) : (
            <ParentSize debounceTime={0}>{({ width }) => children(Math.max(width, 1))}</ParentSize>
          )}
        </div>
      </div>
      <details className="collapse collapse-arrow mt-4 rounded-none border-t border-base-300 bg-base-100">
        <summary className="collapse-title min-h-11 px-4 py-4 sm:px-5 text-sm font-medium">
          Show data table<span className="sr-only">: {title}</span>
        </summary>
        <div className="collapse-content p-0!">
          <ScrollRegion label={`${title} data`} className="max-h-96">
            <table className="table tabular-nums">
              <caption className="sr-only">
                {title}
                {unit ? ` (${unit})` : ""}
              </caption>
              <thead className="sticky top-0 z-10 bg-base-100 text-xs font-medium text-(--color-ink-3) [&_th]:font-medium">
                <tr>
                  <th scope="col">Date / category</th>
                  {series.map((item) => (
                    <th key={item.label} scope="col" className="text-right">
                      {item.label}
                      {unit ? ` (${unit})` : ""}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {!rows.length && (
                  <tr className="h-12">
                    <td colSpan={series.length + 1} className="text-secondary">
                      No recorded categories for these filters.
                    </td>
                  </tr>
                )}
                {rows.map((row) => (
                  <tr key={row.label} className="h-12 hover:bg-base-200">
                    <th scope="row" className="font-normal">
                      {row.label}
                    </th>
                    {row.values.map((value, index) => (
                      <td key={series[index].label} className="text-right">
                        {chartValue(value, unit)}
                      </td>
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
