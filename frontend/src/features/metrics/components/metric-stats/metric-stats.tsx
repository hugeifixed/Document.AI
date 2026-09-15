import { chartValue } from "../../utils/chart-values";
export function MetricStats({ items }: { items: { label: string; value: number | string | null; hint?: string }[] }) {
  return (
    <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {items.map((item) => (
        <div key={item.label} className="stats min-w-0 border border-base-300 bg-base-100 elevation-raised">
          <div className="stat min-w-0">
            <div className="stat-title whitespace-normal text-sm font-medium text-secondary">{item.label}</div>
            <div className="stat-value break-words text-[26px] font-semibold tracking-tight tabular-nums">
              {typeof item.value === "string" ? item.value : chartValue(item.value)}
            </div>
            {item.hint && (
              <div className="stat-desc mt-1 whitespace-normal text-caption text-(--color-ink-3)">{item.hint}</div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
