import { fireEvent, render, screen } from "@testing-library/react";
import { DateFilter } from "./date-filter";
it("keeps draft dates local until validated and applied", () => {
  const change = vi.fn();
  render(
    <DateFilter
      range="custom"
      today="2026-09-01"
      start="2026-08-01"
      end="2026-09-01"
      onChange={change}
      validate={() => "Choose at most 90 inclusive days."}
    />,
  );
  fireEvent.change(screen.getByLabelText(/Start date/), { target: { value: "2026-01-01" } });
  expect(change).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Apply dates" }));
  expect(screen.getByRole("alert")).toHaveTextContent("90");
  for (const name of ["Start date", "End date"]) {
    expect(screen.getByLabelText(new RegExp(name))).toBeInvalid();
    expect(screen.getByLabelText(new RegExp(name))).toHaveAccessibleDescription("Choose at most 90 inclusive days.");
    expect(screen.getByLabelText(new RegExp(name))).toBeRequired();
  }
  expect(change).not.toHaveBeenCalled();
});
