import type { Metrics } from "@/common/types/api";
import { BarChart } from "../bar-chart/bar-chart";
import { chartColors } from "../../utils/chart-values";
import { MetricStats } from "../metric-stats/metric-stats";
export function ReliabilitySection({ data }: { data: Metrics["runs"] }) {
  return (
    <section aria-labelledby="reliability-heading" className="space-y-4">
      <div>
        <h2 id="reliability-heading">Run reliability</h2>
        <p className="mt-1 text-caption text-secondary">
          Finished runs by UTC finish date; processing filters do not apply.
        </p>
      </div>
      <MetricStats
        items={[
          {
            label: "Run success rate",
            value:
              data.success_rate == null
                ? null
                : `${data.success_rate.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`,
            hint: "Succeeded / (succeeded + partial + failed)",
          },
          { label: "Failed runs", value: data.failed },
          {
            label: "Partial runs",
            value: data.partial,
            hint: `${data.cancelled.toLocaleString()} cancelled runs are separate from success rate`,
          },
        ]}
      />
      <BarChart
        title="Daily run outcomes"
        description="Succeeded, failed, partial and cancelled runs remain separate outcomes."
        rows={data.daily.map((d) => ({ label: d.date, values: [d.succeeded, d.failed, d.partial, d.cancelled] }))}
        series={["Succeeded", "Failed", "Partial", "Cancelled"].map((label, i) => ({ label, color: chartColors[i] }))}
      />
    </section>
  );
}
