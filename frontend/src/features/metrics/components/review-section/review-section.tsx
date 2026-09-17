import type { Metrics } from "@/common/types/api";
import { BarChart } from "../bar-chart/bar-chart";
import { chartColors } from "../../utils/chart-values";
import { MetricStats } from "../metric-stats/metric-stats";
export function ReviewSection({ data }: { data: Metrics["review"] }) {
  return (
    <section aria-labelledby="review-heading" className="space-y-4">
      <div>
        <h2 id="review-heading">Review</h2>
        <p className="mt-1 text-caption text-secondary">
          Current backlog in this workspace spans all dates. Decisions below use the selected period.
        </p>
      </div>
      <MetricStats
        items={[
          { label: "Backlog fields", value: data.backlog_fields },
          { label: "Backlog classifications", value: data.backlog_classifications },
          { label: "Grouping reviews", value: data.backlog_segments ?? null },
          {
            label: "Backlog documents",
            value: data.backlog_documents,
            hint: "Distinct documents currently needing review",
          },
          {
            label: "Review decisions",
            value: data.decision_count,
            hint: "Repeated actions count as separate decisions",
          },
          {
            label: "Field correction rate",
            value:
              data.field_correction_rate == null
                ? null
                : `${data.field_correction_rate.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`,
            hint: `${data.field_correction_count.toLocaleString()} corrections / ${data.field_decision_count.toLocaleString()} field decisions`,
          },
        ]}
      />
      <BarChart
        title="Daily review decisions"
        description="Field accept, correct, reject and mark absent; classification accept and reclassify. This is not model accuracy."
        rows={data.daily.map((d) => ({ label: d.date, values: [d.field_decisions, d.classification_decisions] }))}
        series={[
          { label: "Field decisions", color: chartColors[0] },
          { label: "Classification decisions", color: chartColors[3] },
        ]}
      />
    </section>
  );
}
