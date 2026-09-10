import { fireEvent, render, screen } from "@testing-library/react";
import { AsyncButton, ConfidenceCue, StatusChip } from "@/components/ui";

describe("AsyncButton", () => {
  it("exposes the current action and blocks duplicate activation while pending", () => {
    const click = vi.fn();
    const { rerender } = render(<AsyncButton pending={false} pendingLabel="Saving…" onClick={click}>Save</AsyncButton>);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(click).toHaveBeenCalledTimes(1);
    rerender(<AsyncButton pending pendingLabel="Saving…" onClick={click}>Save</AsyncButton>);
    const pending = screen.getByRole("button", { name: "Saving…" });
    expect(pending).toBeDisabled();
    expect(pending).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    fireEvent.click(pending);
    expect(click).toHaveBeenCalledTimes(1);
    rerender(<AsyncButton pending={false} pendingLabel="Saving…" disabled onClick={click}>Save</AsyncButton>);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});

describe("ConfidenceCue (DESIGN.md §6.1 three cues)", () => {
  it("high confidence shows numeric value, word and glyph", () => {
    render(<ConfidenceCue score={0.97} label="ssn" />);
    const el = screen.getByLabelText(/ssn confidence 97 percent, high/i);
    expect(el).toHaveTextContent("97% High");
    expect(el.querySelector("[aria-hidden]")).not.toBeNull();
  });
  it("low confidence says needs review; null says not found", () => {
    render(<ConfidenceCue score={0.4} label="a" />);
    expect(screen.getByLabelText(/needs review/i)).toHaveTextContent("40% Needs review");
    render(<ConfidenceCue score={null} label="b" />);
    expect(screen.getByLabelText(/b not found/i)).toBeInTheDocument();
  });
});

describe("StatusChip", () => {
  it("always carries a text label", () => {
    render(<StatusChip status="needs_review" />);
    expect(screen.getByText("Needs review")).toBeInTheDocument();
  });
});
