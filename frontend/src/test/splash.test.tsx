import { fireEvent, render, screen } from "@testing-library/react";
import { Splash } from "@/components/Splash";

describe("Splash (DESIGN.md §9.5)", () => {
  it("announces the session check and shows the three statements", () => {
    render(<Splash />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("DocAI");
    expect(screen.getByRole("status")).toHaveTextContent("Checking your session…");
    expect(screen.getByText(/grounded in the page it came from/)).toBeInTheDocument();
    expect(screen.getByText(/audit trail on every run/)).toBeInTheDocument();
    expect(screen.getByText(/where the model is unsure/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("on error shows the notice with Retry, stops the sweep and says it is not connected", () => {
    const retry = vi.fn();
    render(<Splash error onRetry={retry} />);
    expect(screen.getByRole("status")).toHaveTextContent("Not connected");
    expect(screen.getByRole("alert")).toHaveTextContent(/couldn’t connect to DocAI/);
    expect(document.querySelector(".splash-sweep")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});
