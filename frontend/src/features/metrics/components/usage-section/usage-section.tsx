import type { MetricsUsage } from "@/common/types/api";
import { SelectControl } from "@/common/components/ui/select-control/select-control";
import { LineChart } from "../line-chart/line-chart";
import { chartColors } from "../chart-types";
import { MetricStats } from "../metric-stats/metric-stats";
export function UsageSection({
  data,
  filters,
  onChange,
}: {
  data: MetricsUsage;
  filters: { provider?: string; deployment?: string; stage?: string };
  onChange: (changes: Record<string, string>) => void;
}) {
  const options = [
    { key: "provider", label: "Provider", values: data.filter_options.providers },
    { key: "deployment", label: "Deployment", values: data.filter_options.deployments },
    { key: "stage", label: "Stage", values: data.filter_options.stages },
  ] as const;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-4">
        {options.map((option) => (
          <label htmlFor={`metrics-${option.key}`} key={option.key} className="field w-full sm:w-48">
            <span className="label">{option.label}</span>
            <SelectControl
              id={`metrics-${option.key}`}
              value={filters[option.key] || ""}
              onChange={(e) => onChange({ [option.key]: e.target.value })}
            >
              <option value="">All {option.label.toLowerCase()}s</option>
              {filters[option.key] && !option.values.includes(filters[option.key]!) && (
                <option value={filters[option.key]}>{filters[option.key]}</option>
              )}
              {option.values.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </SelectControl>
          </label>
        ))}
      </div>
      <p className="text-caption text-secondary">
        Provider, deployment and stage affect LLM usage only. Recorded responses include retries.
      </p>
      <MetricStats
        items={[
          { label: "Recorded responses", value: data.calls },
          {
            label: "Measured tokens",
            value: data.total_tokens,
            hint: "Known totals only; missing measurements are unknown",
          },
          {
            label: "Measurement coverage",
            value: data.calls
              ? `${((100 * data.measured_calls) / data.calls).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`
              : "No responses",
            hint: `${data.measured_calls.toLocaleString()} of ${data.calls.toLocaleString()} responses have measured totals`,
          },
        ]}
      />
      <LineChart
        title="Daily measured tokens"
        description="Known token totals including retry responses. Unknown totals are gaps; cached and reasoning tokens are subsets."
        rows={data.daily.map((d) => ({ label: d.date, values: [d.total_tokens] }))}
        series={[{ label: "Measured tokens", color: chartColors[0] }]}
      />
    </div>
  );
}
