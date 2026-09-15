import { render, screen } from "@testing-library/react";
import { metrics } from "../../testing/fixtures";
import { ProcessingSection } from "./processing-section";
it("shows the recorded metric and its scope", () => {
  render(<ProcessingSection data={metrics.processing} onChange={() => {}} />);
  expect(screen.getByText("Completed jobs")).toBeVisible();
});
