import { render, screen } from "@testing-library/react";
import { metrics } from "../../testing/fixtures";
import { ReviewSection } from "./review-section";
it("shows the recorded metric and its scope", () => {
  render(<ReviewSection data={metrics.review} />);
  expect(screen.getByText("20%")).toBeVisible();
});
