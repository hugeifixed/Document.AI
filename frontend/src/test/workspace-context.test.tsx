import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { WorkspaceContextBreadcrumb } from "@/layouts/AppShell";

describe("WorkspaceContextBreadcrumb", () => {
  it("presents project and dataset context as useful navigation", () => {
    render(
      <MemoryRouter>
        <WorkspaceContextBreadcrumb
          projectName="Sample banking documents"
          datasetName="W-2 validation set"
        />
      </MemoryRouter>,
    );

    const context = screen.getByRole("navigation", { name: "Working context" });
    expect(context).toHaveClass("breadcrumbs");
    expect(screen.getByRole("link", { name: "Project: Sample banking documents" })).toHaveAttribute("href", "/projects");
    expect(screen.getByRole("link", { name: "Dataset: W-2 validation set" })).toHaveAttribute("href", "/datasets");
  });
});
