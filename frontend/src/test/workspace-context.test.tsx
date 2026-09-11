import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { WorkspaceContextBreadcrumb } from "@/layouts/AppShell";
import { useWorkingContext } from "@/workspace/context";

describe("WorkspaceContextBreadcrumb", () => {
  beforeEach(() => {
    useWorkingContext.getState().clear();
  });

  it("presents project and dataset context as useful navigation", () => {
    render(
      <MemoryRouter>
        <WorkspaceContextBreadcrumb projectName="Sample banking documents" datasetName="W-2 validation set" />
      </MemoryRouter>,
    );

    const context = screen.getByRole("navigation", { name: "Working context" });
    expect(context).toHaveClass("breadcrumbs");
    expect(screen.getByRole("link", { name: "Project: Sample banking documents" })).toHaveAttribute(
      "href",
      "/projects",
    );
    expect(screen.getByRole("link", { name: "Dataset: W-2 validation set" })).toHaveAttribute("href", "/datasets");
  });

  it("clears the dataset when the project changes", () => {
    act(() => {
      useWorkingContext.getState().selectDatasetForProject("project-1", "dataset-1");
      useWorkingContext.getState().selectProject("project-2");
    });

    expect(useWorkingContext.getState()).toMatchObject({ projectId: "project-2", datasetId: null });
  });

  it("cannot select a dataset without a project", () => {
    act(() => useWorkingContext.getState().selectDataset("dataset-1"));

    expect(useWorkingContext.getState()).toMatchObject({ projectId: null, datasetId: null });
  });

  it("repairs an orphaned dataset when the empty project is selected", () => {
    useWorkingContext.setState({ projectId: null, datasetId: "orphaned-dataset" });

    act(() => useWorkingContext.getState().selectProject(null));

    expect(useWorkingContext.getState()).toMatchObject({ projectId: null, datasetId: null });
  });
});
