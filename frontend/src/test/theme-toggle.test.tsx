import { fireEvent, render, screen } from "@testing-library/react";
import { ThemeToggle } from "@/components/ThemeToggle";
import { applyTheme, usePrefs } from "@/store/prefs";

describe("ThemeToggle", () => {
  beforeEach(() => {
    usePrefs.setState({ theme: "light" });
    applyTheme("light");
  });

  it("switches between explicit dark and light preferences", () => {
    render(<ThemeToggle />);

    fireEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(usePrefs.getState().theme).toBe("dark");

    fireEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(usePrefs.getState().theme).toBe("light");
  });

  it("offers the opposite of the active system theme", () => {
    usePrefs.setState({ theme: "system" });
    render(<ThemeToggle />);

    expect(screen.getByRole("button", { name: "Switch to dark theme" })).toBeInTheDocument();
  });
});
