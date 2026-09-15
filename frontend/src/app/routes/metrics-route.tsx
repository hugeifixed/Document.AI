import { MetricsDashboard } from "@/features/metrics/components/metrics-dashboard";
export function MetricsRoute(props: { projectId: string | null; datasetId: string | null; canViewUsage: boolean }) {
  return <MetricsDashboard {...props} />;
}
