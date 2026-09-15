import { fireEvent, render, screen } from "@testing-library/react";
import { BarChart } from "./bar-chart";
vi.mock("@visx/responsive", () => ({
  ParentSize: ({ children }: { children: (size: { width: number }) => React.ReactNode }) => children({ width: 400 }),
}));
it("offers keyboard/touch values through one control and dismisses its tooltip", () => {
  render(
    <BarChart
      title="Daily trend"
      description="UTC days"
      rows={[
        { label: "2026-09-01", values: [10, null] },
        { label: "2026-09-02", values: [0, 4] },
      ]}
      series={[
        { label: "A", color: "currentColor" },
        { label: "B", color: "currentColor" },
      ]}
    />,
  );
  const control = screen.getByRole("combobox", { name: "Inspect Daily trend" });
  fireEvent.change(control, { target: { value: "2026-09-01" } });
  expect(screen.getByRole("tooltip")).toHaveTextContent("A: 10");
  expect(screen.getByRole("tooltip")).toHaveTextContent("B: Unknown");
  fireEvent.keyDown(control, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
});
