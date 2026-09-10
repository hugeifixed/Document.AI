import { screen } from "@testing-library/react";
import { announce } from "@/a11y/announce";

it("cancels stale pending feedback without cancelling a newer result", () => {
  vi.useFakeTimers();
  try {
    const finishedQuickly = announce("Saving…");
    finishedQuickly();
    vi.advanceTimersByTime(200);
    expect(screen.getByRole("status")).toBeEmptyDOMElement();

    const pending = announce("Saving…");
    announce("Saved successfully");
    pending();
    vi.advanceTimersByTime(200);
    expect(screen.getByRole("status")).toHaveTextContent("Saved successfully");
  } finally { vi.useRealTimers(); }
});
