import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { NotFound } from "@/pages/NotFound";

function Location() {
  return <output>{useLocation().pathname}</output>;
}

describe("NotFound", () => {
  it("explains the missing location and provides recovery actions", () => {
    render(<MemoryRouter initialEntries={["/projects", "/ht"]} initialIndex={1}>
      <Routes>
        <Route path="/projects" element={<Location />} />
        <Route path="*" element={<><NotFound /><Location /></>} />
      </Routes>
    </MemoryRouter>);

    const heading = screen.getByRole("heading", { name: "Page not found" });
    expect(heading).toHaveFocus();
    expect(screen.getByText("/ht", { selector: "code" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");

    fireEvent.click(screen.getByRole("button", { name: "Go back" }));
    expect(screen.getByText("/projects")).toBeInTheDocument();
  });
});
