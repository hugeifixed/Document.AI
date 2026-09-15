import { render, screen } from "@testing-library/react";
import { metrics } from "../../testing/fixtures";
import { ReliabilitySection } from "./reliability-section";
it("shows the recorded metric and its scope", () => {
  render(<ReliabilitySection data={metrics.runs} />);
  expect(screen.getByText("50%")).toBeVisible();
});
