import { dashboardParams, nextResultsAction, nextRunAction, nextWorkspaceAction } from "@/journey/guidance";
import { testDashboard, testRun } from "@/test/fixtures";

const roles = ["docai_operators", "docai_reviewers", "docai_approvers"];
const workspaceAction = (dashboard = testDashboard(), activeRoles = roles) =>
  nextWorkspaceAction({ dashboard, projectId: "project-1", datasetId: "dataset-1", roles: activeRoles });

describe("journey guidance", () => {
  it("only sends a dataset scope when its project is known", () => {
    expect(dashboardParams(null, "dataset-1")).toEqual({});
    expect(dashboardParams("project-1", null)).toEqual({ project: "project-1" });
    expect(dashboardParams("project-1", "dataset-1")).toEqual({
      project: "project-1",
      dataset: "dataset-1",
    });
  });

  it("guides users through missing workspace prerequisites", () => {
    const empty = testDashboard({ projects: 0, datasets: 0 });
    expect(nextWorkspaceAction({ dashboard: empty, projectId: null, datasetId: null, roles })).toMatchObject({
      label: "Create project",
      to: "/projects",
    });
    expect(nextWorkspaceAction({ dashboard: empty, projectId: null, datasetId: null, roles: [] }).label).toBe(
      "View projects",
    );
    expect(nextWorkspaceAction({ dashboard: testDashboard(), projectId: null, datasetId: null, roles }).label).toBe(
      "Choose project",
    );
    expect(nextWorkspaceAction({ dashboard: empty, projectId: "project-1", datasetId: null, roles })).toMatchObject({
      label: "Create dataset",
      to: "/datasets",
    });
    expect(nextWorkspaceAction({ dashboard: empty, projectId: "project-1", datasetId: null, roles: [] }).label).toBe(
      "View datasets",
    );
    expect(
      nextWorkspaceAction({ dashboard: testDashboard(), projectId: "project-1", datasetId: null, roles }).label,
    ).toBe("Choose dataset");
  });

  it("prioritizes active processing, upload, and validation recovery", () => {
    const queued = testDashboard({ review_queue: { fields: 0, classifications: 0 } });
    queued.guidance.latest_run!.status = "queued";
    expect(workspaceAction(queued)).toMatchObject({ title: "Run is queued", label: "View run progress" });
    expect(workspaceAction(testDashboard({ review_queue: { fields: 0, classifications: 0 } })).title).toBe(
      "Run is processing",
    );

    const empty = testDashboard();
    empty.guidance.latest_run = null;
    empty.guidance.documents = { total: 0, runnable: 0, blocked: 0, new_for_run: 0 };
    expect(workspaceAction(empty).label).toBe("Upload documents");

    empty.guidance.documents = { total: 1, runnable: 0, blocked: 1, new_for_run: 0 };
    expect(workspaceAction(empty)).toMatchObject({ label: "Review documents", to: "/datasets?status=rejected" });
  });

  it("guides a ready dataset into a prefilled run", () => {
    const dashboard = testDashboard({
      review_queue: { fields: 0, classifications: 0 },
      recent_runs: [],
      runs: {},
      guidance: {
        ...testDashboard().guidance,
        documents: { total: 3, runnable: 3, blocked: 0, new_for_run: 3 },
        latest_run: null,
      },
    });

    const action = workspaceAction(dashboard);

    expect(action.label).toBe("Start a run");
    expect(action.to).toBe("/runs?dataset=dataset-1&workflow=workflow-1");
    expect(action.description).toContain("3 documents");
  });

  it("surfaces a missing workflow before offering a run", () => {
    const dashboard = testDashboard({
      review_queue: { fields: 0, classifications: 0 },
      guidance: {
        ...testDashboard().guidance,
        documents: { total: 2, runnable: 2, blocked: 0, new_for_run: 2 },
        workflows: { runnable: 0, approved: 0, draft: 0, suggested: null },
        latest_run: null,
      },
    });

    expect(workspaceAction(dashboard)).toMatchObject({
      label: "Create workflow version",
      to: "/workflows/new",
    });
    expect(workspaceAction(dashboard, [])).toMatchObject({
      label: "View workflow versions",
      to: "/configurations",
    });
  });

  it("keeps a failed run visible before suggesting another run", () => {
    const dashboard = testDashboard({
      review_queue: { fields: 0, classifications: 0 },
      guidance: {
        ...testDashboard().guidance,
        documents: { total: 2, runnable: 2, blocked: 0, new_for_run: 0 },
        latest_run: {
          ...testDashboard().guidance.latest_run!,
          status: "failed",
          failed: 2,
        },
      },
    });

    expect(workspaceAction(dashboard)).toMatchObject({
      label: "Review run failures",
      to: "/runs/run-1",
    });
  });

  it("selects each completed-workspace handoff from lifecycle facts", () => {
    const dashboard = testDashboard();
    dashboard.guidance.latest_run!.status = "succeeded";
    dashboard.guidance.latest_run!.guidance.review = { fields: 1, classifications: 0 };
    expect(workspaceAction(dashboard, []).label).toBe("View review queue");

    dashboard.guidance.latest_run!.guidance.review = { fields: 0, classifications: 0 };
    dashboard.review_queue = { fields: 0, classifications: 0 };
    dashboard.guidance.latest_run!.guidance.ground_truth.labels = 1;
    expect(workspaceAction(dashboard).to).toBe("/evaluation?run=run-1");

    dashboard.guidance.latest_run!.guidance.evaluations.count = 1;
    dashboard.guidance.latest_run!.guidance.export_ready = true;
    expect(workspaceAction(dashboard).to).toBe("/exports?run=run-1");

    dashboard.guidance.latest_run!.guidance.evaluations.count = 0;
    dashboard.guidance.latest_run!.guidance.export_ready = false;
    dashboard.guidance.latest_run!.guidance.ground_truth.labels = 0;
    expect(workspaceAction(dashboard).label).toBe("Label documents");

    dashboard.guidance.dataset!.is_production = true;
    expect(workspaceAction(dashboard).to).toBe("/results?run=run-1");
  });

  it("prioritizes the scoped review backlog over starting another run", () => {
    const dashboard = testDashboard({
      review_queue: { fields: 1, classifications: 1 },
      guidance: {
        ...testDashboard().guidance,
        documents: { total: 4, runnable: 4, blocked: 0, new_for_run: 2 },
        latest_run: {
          ...testDashboard().guidance.latest_run!,
          status: "succeeded",
          guidance: {
            ...testDashboard().guidance.latest_run!.guidance,
            review: { fields: 0, classifications: 0 },
          },
        },
      },
    });

    expect(workspaceAction(dashboard)).toMatchObject({
      title: "2 results need human review",
      label: "Continue review",
      to: "/review",
    });
  });

  it("routes completed work through review, evaluation, and export", () => {
    const reviewRun = testRun({
      status: "succeeded",
      guidance: {
        review: { fields: 2, classifications: 0 },
        results: 4,
        ground_truth: { labels: 3, documents: 1 },
        evaluations: { count: 0, latest_id: null, has_ground_truth: null },
        export_ready: true,
      },
    });
    expect(nextRunAction(reviewRun, roles)?.to).toBe("/review?run=run-1");

    const evaluated = testRun({
      status: "succeeded",
      guidance: {
        ...reviewRun.guidance!,
        review: { fields: 0, classifications: 0 },
        evaluations: { count: 1, latest_id: "evaluation-1", has_ground_truth: true },
      },
    });
    expect(nextResultsAction(evaluated, roles)?.to).toBe("/exports?run=run-1");
  });

  it("resolves run detail actions without hiding failures or read-only review", () => {
    const failed = testRun({ status: "partial", failed_items: 1 });
    expect(nextRunAction(failed, roles)).toMatchObject({ label: "View failed documents", to: "#run-items" });
    expect(nextRunAction(failed, [])?.description).toContain("An operator");

    const review = testRun({
      status: "succeeded",
      guidance: { ...testRun().guidance!, review: { fields: 1, classifications: 0 } },
    });
    expect(nextRunAction(review, [])?.label).toBe("View review queue");

    const evaluate = testRun({
      status: "succeeded",
      guidance: { ...testRun().guidance!, ground_truth: { labels: 1, documents: 1 } },
    });
    expect(nextRunAction(evaluate, roles)?.to).toBe("/evaluation?run=run-1");

    const exported = testRun({
      status: "succeeded",
      guidance: {
        ...testRun().guidance!,
        evaluations: { count: 1, latest_id: "evaluation-1", has_ground_truth: true },
        export_ready: true,
      },
    });
    expect(nextRunAction(exported, roles)?.to).toBe("/exports?run=run-1");

    const results = testRun({ status: "succeeded", guidance: { ...testRun().guidance!, results: 2 } });
    expect(nextRunAction(results, roles)?.to).toBe("/results?run=run-1");
    expect(nextRunAction(testRun({ guidance: undefined }), roles)).toBeNull();
    expect(nextRunAction(testRun({ status: "running" }), roles)).toBeNull();
  });

  it("resolves results actions for reviewer, operator, and delivery states", () => {
    const review = testRun({
      guidance: { ...testRun().guidance!, review: { fields: 1, classifications: 0 } },
    });
    expect(nextResultsAction(review, roles)?.label).toBe("Continue review");
    expect(nextResultsAction(review, [])?.label).toBe("View review queue");

    const evaluate = testRun({
      guidance: { ...testRun().guidance!, ground_truth: { labels: 1, documents: 1 } },
    });
    expect(nextResultsAction(evaluate, roles)?.to).toBe("/evaluation?run=run-1");

    const exported = testRun({ guidance: { ...testRun().guidance!, export_ready: true } });
    expect(nextResultsAction(exported, roles)?.to).toBe("/exports?run=run-1");
    expect(nextResultsAction(testRun({ guidance: undefined }), roles)).toBeNull();
    expect(nextResultsAction(testRun(), roles)).toBeNull();
  });
});
