import { render, screen, within } from "@testing-library/react";
import { ChartFrame } from "./chart-frame";
it("provides named exact-value tables for unknown and zero data", () => {
  render(
    <ChartFrame
      title="Tokens"
      description="Measured only"
      rows={[
        { label: "2026-09-01", values: [null] },
        { label: "2026-09-02", values: [0] },
      ]}
      series={[{ label: "Measured tokens", color: "currentColor" }]}
    >
      {() => <span>Plot</span>}
    </ChartFrame>,
  );
  expect(screen.getByText("No recorded values for these filters.")).toBeVisible();
  const disclosure = screen.getByText("Show data table").closest("details")!;
  disclosure.open = true;
  const table = screen.getByRole("table", { name: "Tokens" });
  expect(within(table).getByText("Unknown")).toBeVisible();
  expect(within(table).getByText("0")).toBeVisible();
});
