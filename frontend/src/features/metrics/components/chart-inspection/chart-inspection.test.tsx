import { fireEvent, render, screen } from "@testing-library/react";
import { useChartTooltip } from "../../hooks/use-chart-tooltip";
import type { ChartRow } from "../../types/chart-types";
import { ChartInspection } from "./chart-inspection";
function Inspection({ rows }: { rows: ChartRow[] }) {
  const tooltip = useChartTooltip(rows);
  return (
    <ChartInspection
      title="Measurements"
      description="Recorded"
      rows={rows}
      series={[{ label: "Tokens", color: "currentColor" }]}
      tooltip={tooltip}
      id="inspection"
      width={400}
    />
  );
}
it("derives inspected values from refreshed rows and clears absent identities", () => {
  const { rerender } = render(<Inspection rows={[{ label: "day", values: [10] }]} />);
  const control = screen.getByRole("combobox");
  fireEvent.change(control, { target: { value: "day" } });
  expect(screen.getByRole("tooltip")).toHaveTextContent("Tokens: 10");
  rerender(<Inspection rows={[{ label: "day", values: [0] }]} />);
  expect(screen.getByRole("tooltip")).toHaveTextContent("Tokens: 0");
  rerender(<Inspection rows={[{ label: "day", values: [null] }]} />);
  expect(screen.getByRole("tooltip")).toHaveTextContent("Tokens: Unknown");
  rerender(<Inspection rows={[{ label: "different", values: [100] }]} />);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  expect(control).toHaveValue("");
  expect(control).not.toHaveAttribute("aria-describedby");
});
