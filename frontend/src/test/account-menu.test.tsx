import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AccountMenu } from "@/components/AccountMenu";
import type { Me } from "@/api/types";

const user: Me = {
  username: "preview",
  is_staff: true,
  roles: ["docai_operators", "docai_reviewers"],
  platform_version: "1",
  adapters: { layout: "mock", llm: "mock", task_runner: "sync" },
  tools: { request_profiler: "/admin/profiler/" },
};

describe("AccountMenu", () => {
  it("shows identity and account actions, then logs out once", async () => {
    const logout = vi.fn().mockResolvedValue(undefined);
    const startTour = vi.fn();
    render(<MemoryRouter><AccountMenu user={user} pending={false} onLogout={logout} onStartTour={startTour} /></MemoryRouter>);

    expect(screen.getByRole("button", { name: "Account menu for preview" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Administrator")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
    expect(screen.getByRole("link", { name: "Admin" })).toHaveAttribute("href", "/admin/");
    expect(screen.getByRole("link", { name: "Request profiler" })).toHaveAttribute("href", "/admin/profiler/");
    expect(screen.getByRole("link", { name: "API documentation" })).toHaveAttribute("href", "/api/docs/");
    fireEvent.click(screen.getByRole("button", { name: "Take a tour" }));
    await waitFor(() => expect(startTour).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Log out" }));
    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1));
  });

  it("hides staff actions and exposes pending logout state", () => {
    render(<MemoryRouter><AccountMenu user={{ ...user, is_staff: false }} pending onLogout={() => {}} onStartTour={() => {}} /></MemoryRouter>);

    expect(screen.getByText("Operator · Reviewer")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Request profiler" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Logging out…" })).toBeDisabled();
  });
});
