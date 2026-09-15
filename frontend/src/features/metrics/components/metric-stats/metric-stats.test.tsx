import { render, screen } from "@testing-library/react";
import { MetricStats } from "./metric-stats";
it("distinguishes unknown totals from measured zero", () => {
  render(
    <MetricStats
      items={[
        { label: "Unknown tokens", value: null },
        { label: "No calls", value: 0 },
      ]}
    />,
  );
  expect(screen.getByText("Unknown")).toBeVisible();
  expect(screen.getByText("0")).toBeVisible();
});
