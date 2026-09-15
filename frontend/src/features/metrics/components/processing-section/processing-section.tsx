import type { ReactNode } from "react";
import { Field } from "@/common/components/ui/field/field";
import type { Metrics } from "@/common/types/api";
import { SelectControl } from "@/common/components/ui/select-control/select-control";
import { BarChart } from "../bar-chart/bar-chart";
import { LineChart } from "../line-chart/line-chart";
import { chartColors } from "../../utils/chart-values";
import { MetricStats } from "../metric-stats/metric-stats";
export function ProcessingSection({
  data,
  children,
  documentType,
  status,
  onChange,
}: {
  data?: Metrics["processing"];
  children?: ReactNode;
  documentType?: string;
  status?: string;
  onChange: (changes: Record<string, string>) => void;
}) {
  const documentTypes = data?.document_type_options ?? [];
  const duration = (value: number | null) =>
    value == null ? null : `${(value / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 })} s`;
  return (
    <section aria-labelledby="processing-heading" className="space-y-4">
      <div>
        <h2 id="processing-heading">Processing</h2>
        <p className="mt-1 text-caption text-secondary">
          Document executions completed in this period. Reruns count separately; internal retries count once.
        </p>
      </div>
      <div className="flex flex-wrap gap-4" aria-label="Processing filters">
        <Field id="metrics-document-type" label="Document type" className="w-full sm:w-56">
          <SelectControl
            id="metrics-document-type"
            value={documentType || ""}
            onChange={(e) => onChange({ document_type: e.target.value })}
          >
            <option value="">All document types</option>
            {documentType && !documentTypes.some((o) => o.key === documentType) && (
              <option value={documentType}>{documentType}</option>
            )}
            {documentTypes.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </SelectControl>
        </Field>
        <Field id="metrics-job-status" label="Job status" className="w-full sm:w-44">
          <SelectControl
            id="metrics-job-status"
            value={status || ""}
            onChange={(e) => onChange({ status: e.target.value })}
          >
            <option value="">All completed jobs</option>
            <option value="succeeded">Succeeded</option>
            <option value="failed">Failed</option>
          </SelectControl>
        </Field>
      </div>
      <p className="text-caption text-secondary">Document type and job status affect Processing only.</p>
      {children}
      {data && (
        <>
          <MetricStats
            items={[
              { label: "Completed jobs", value: data.completed_jobs },
              {
                label: "Median duration",
                value: duration(data.median_duration_ms),
                hint: `${data.duration_sample_count.toLocaleString()} recorded durations`,
              },
              {
                label: "P95 duration",
                value: duration(data.p95_duration_ms),
                hint: "Recorded final attempt; excludes queue delay and earlier attempts",
              },
            ]}
          />
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <BarChart
              title="Daily job volume"
              description="Completed executions by UTC completion date."
              rows={data.daily.map((d) => ({ label: d.date, values: [d.succeeded, d.failed] }))}
              series={[
                { label: "Succeeded", color: chartColors[0] },
                { label: "Failed", color: chartColors[1] },
              ]}
            />
            <LineChart
              title="Daily duration"
              description="Recorded final-attempt duration; missing measurements remain unknown."
              unit="s"
              rows={data.daily.map((d) => ({
                label: d.date,
                values: [
                  d.median_duration_ms == null ? null : d.median_duration_ms / 1000,
                  d.p95_duration_ms == null ? null : d.p95_duration_ms / 1000,
                ],
              }))}
              series={[
                { label: "Median", color: chartColors[0] },
                { label: "P95", color: chartColors[3] },
              ]}
            />
            <BarChart
              title="Recorded document types"
              description="Executions containing each reviewed or recorded type. Mixed-type counts are not additive."
              rows={data.by_document_type.map((d) => ({ label: d.label, values: [d.executions] }))}
              series={[{ label: "Executions", color: chartColors[0] }]}
            />
            <BarChart
              title="Failed jobs by phase"
              description="Broad recorded failure phase; unknown means no recognized phase was recorded."
              rows={data.failures_by_phase.map((d) => ({ label: d.label, values: [d.count] }))}
              series={[{ label: "Failed jobs", color: chartColors[1] }]}
            />
          </div>
        </>
      )}
    </section>
  );
}
