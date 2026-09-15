import { render, screen } from "@testing-library/react";
import { usage } from "../../testing/fixtures";
import { UsageSection } from "./usage-section";
it("labels partial measurement coverage rather than fabricating totals", () => {
  render(<UsageSection data={{ ...usage, total_tokens: null, measured_calls: 0 }} filters={{}} onChange={() => {}} />);
  expect(screen.getByText("Unknown")).toBeVisible();
  expect(screen.getByText("0%")).toBeVisible();
  expect(screen.getByText("0 of 5 responses have measured totals")).toBeVisible();
});
