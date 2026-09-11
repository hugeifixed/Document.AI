import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { RouteError } from "@/components/RouteError";

function BrokenPage(): never {
  throw new Error("The review workspace failed to render.");
}

describe("RouteError", () => {
  it("offers a clear recovery path for render failures", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const router = createMemoryRouter([{ path: "/", element: <BrokenPage />, errorElement: <RouteError /> }]);
    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "Something went wrong" })).toBeInTheDocument();
    expect(screen.getByText("The review workspace failed to render.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload page" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    consoleError.mockRestore();
  });
});
