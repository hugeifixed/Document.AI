import { render, screen } from "@testing-library/react";
import { MetricsRoute } from "./metrics-route";
vi.mock("@/features/metrics/components/metrics-dashboard", () => ({
  MetricsDashboard: (props: { projectId: string; datasetId: string; canViewUsage: boolean }) => (
    <p>
      {props.projectId} / {props.datasetId} / {String(props.canViewUsage)}
    </p>
  ),
}));
it("composes scope and usage access without another request", () => {
  render(<MetricsRoute projectId="p" datasetId="d" canViewUsage />);
  expect(screen.getByText("p / d / true")).toBeVisible();
});
