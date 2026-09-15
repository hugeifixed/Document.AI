import { act, fireEvent, render, screen } from "@testing-library/react";
import { LineChart } from "./line-chart";
vi.mock("@visx/responsive", () => ({
  ParentSize: ({ children }: { children: (size: { width: number }) => React.ReactNode }) => children({ width: 400 }),
}));
it("offers keyboard/touch values through one control and dismisses its tooltip", () => {
  render(
    <LineChart
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

it("keeps focused inspection open across pointer leave, then dismisses on blur", () => {
  const { container } = render(
    <LineChart
      title="Focused trend"
      description="UTC days"
      rows={[{ label: "2026-09-01", values: [10] }]}
      series={[{ label: "Measured", color: "currentColor" }]}
    />,
  );
  const control = screen.getByRole("combobox", { name: "Inspect Focused trend" });
  act(() => control.focus());
  fireEvent.change(control, { target: { value: "2026-09-01" } });
  fireEvent.pointerLeave(container.querySelector("svg[aria-labelledby]")!);
  fireEvent.blur(screen.getByRole("option", { name: "2026-09-01" }), { relatedTarget: control });
  expect(control).toHaveFocus();
  expect(screen.getByRole("tooltip")).toHaveTextContent("Measured: 10");
  act(() => control.blur());
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
});
