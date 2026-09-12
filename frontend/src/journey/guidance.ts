import { useQuery } from "@tanstack/react-query";
import { get } from "@/api/client";
import type { Dashboard, Run, RunGuidance } from "@/api/types";
import { dashboardPollingInterval } from "@/runs/lifecycle";

export type JourneyAction = {
  title: string;
  description: string;
  label: string;
  to: string;
};

const hasRole = (roles: string[], role: string) => roles.includes(role);
const plural = (count: number, singular: string, pluralValue = `${singular}s`) =>
  `${count.toLocaleString()} ${count === 1 ? singular : pluralValue}`;

export function dashboardParams(projectId: string | null, datasetId: string | null) {
  return {
    ...(projectId ? { project: projectId } : {}),
    ...(projectId && datasetId ? { dataset: datasetId } : {}),
  };
}

export function useJourneyDashboard(projectId: string | null, datasetId: string | null) {
  return useQuery({
    queryKey: ["dashboard", projectId, datasetId],
    queryFn: ({ signal }) => get<Dashboard>("/dashboard/", dashboardParams(projectId, datasetId), { signal }),
    refetchInterval: (query) => dashboardPollingInterval(query.state.data),
  });
}

export function nextWorkspaceAction({
  dashboard,
  projectId,
  datasetId,
  roles,
}: {
  dashboard: Dashboard;
  projectId: string | null;
  datasetId: string | null;
  roles: string[];
}): JourneyAction {
  const canOperate = hasRole(roles, "docai_operators");
  const canReview = hasRole(roles, "docai_reviewers");

  if (!projectId) {
    return {
      title: dashboard.projects ? "Choose a project to continue" : "Create the first project",
      description: dashboard.projects
        ? "Your project selection scopes datasets, workflow versions, runs, and results."
        : canOperate
          ? "Start with the business use case that will own the documents and processing history."
          : "An operator needs to create the first project before processing can begin.",
      label: dashboard.projects ? "Choose project" : canOperate ? "Create project" : "View projects",
      to: "/projects",
    };
  }

  if (!datasetId) {
    return {
      title: dashboard.datasets ? "Choose a dataset to continue" : "Create the first dataset",
      description: dashboard.datasets
        ? "Select the document collection you want to upload, process, review, or evaluate."
        : canOperate
          ? "A dataset keeps documents and their intended development or production use together."
          : "An operator needs to create a dataset for this project.",
      label: dashboard.datasets ? "Choose dataset" : canOperate ? "Create dataset" : "View datasets",
      to: "/datasets",
    };
  }

  const facts = dashboard.guidance;
  const run = facts.latest_run;
  if (facts.documents.total === 0) {
    return {
      title: "Upload documents",
      description:
        "Add source files to the selected dataset. Validation happens during upload; model processing starts with a run.",
      label: "Upload documents",
      to: "/datasets",
    };
  }

  if (facts.documents.runnable === 0) {
    return {
      title: "Resolve document validation issues",
      description: `${plural(facts.documents.blocked, "document")} cannot be included in a run yet. Open the dataset to see the reason.`,
      label: "Review documents",
      to: "/datasets?status=rejected",
    };
  }

  if (facts.workflows.runnable === 0) {
    return {
      title: "Add a workflow version",
      description: canOperate
        ? "Define how these documents should be classified, split, or extracted before starting a run."
        : "An operator needs to add a workflow version before this dataset can be processed.",
      label: canOperate ? "Create workflow version" : "View workflow versions",
      to: canOperate ? "/workflows/new" : "/configurations",
    };
  }

  if (run?.failed) {
    return {
      title: `${plural(run.failed, "document")} failed during processing`,
      description:
        "Open the run to inspect each failure and retry eligible documents without repeating successful work.",
      label: "Review run failures",
      to: `/runs/${run.id}`,
    };
  }

  const reviewCount = dashboard.review_queue.fields + dashboard.review_queue.classifications;
  if (reviewCount > 0) {
    return {
      title: `${plural(reviewCount, "result")} ${reviewCount === 1 ? "needs" : "need"} human review`,
      description: canReview
        ? "Resolve low-confidence, ungrounded, or validation-flagged results before delivery."
        : "A reviewer needs to resolve the flagged results before the workflow is complete.",
      label: canReview ? "Continue review" : "View review queue",
      to: "/review",
    };
  }

  if (run && ["queued", "running"].includes(run.status)) {
    return {
      title: run.status === "queued" ? "Run is queued" : "Run is processing",
      description: `${run.processed.toLocaleString()} of ${run.total.toLocaleString()} documents have reached a terminal state. Processing continues if you leave this page.`,
      label: "View run progress",
      to: `/runs/${run.id}`,
    };
  }

  if (!run || facts.documents.new_for_run > 0 || run.status === "cancelled") {
    const suggested = facts.workflows.suggested;
    const query = new URLSearchParams({ dataset: datasetId });
    if (suggested) query.set("workflow", suggested.id);
    return {
      title: "Documents are ready to process",
      description: `${plural(facts.documents.runnable, "document")} can be processed${suggested ? ` with ${suggested.name} v${suggested.version}` : ""}. Confirm the workflow and run size before execution.`,
      label: "Start a run",
      to: `/runs?${query.toString()}`,
    };
  }

  if (!facts.dataset?.is_production && run.guidance.ground_truth.labels > 0 && run.guidance.evaluations.count === 0) {
    return {
      title: "Measure this run against ground truth",
      description: `${plural(run.guidance.ground_truth.labels, "final label")} are available for an accuracy evaluation.`,
      label: "Evaluate run",
      to: `/evaluation?run=${run.id}`,
    };
  }

  if (run.guidance.evaluations.count > 0 && run.guidance.export_ready) {
    return {
      title: "Results are ready to share",
      description: "Download the stored results with their configuration snapshot and review history.",
      label: "Export results",
      to: `/exports?run=${run.id}`,
    };
  }

  if (!facts.dataset?.is_production && run.guidance.ground_truth.labels === 0 && canReview) {
    return {
      title: "Add ground truth for an accuracy evaluation",
      description:
        "Create final labels for representative documents, or inspect operational quality indicators without them.",
      label: "Label documents",
      to: "/labeling",
    };
  }

  return {
    title: "Inspect the completed results",
    description: "Check extracted values, confidence, validation, and grounding before evaluating or exporting them.",
    label: "View extracted results",
    to: `/results?run=${run.id}`,
  };
}

export function nextRunAction(run: Run, roles: string[]): JourneyAction | null {
  const facts: RunGuidance | undefined = run.guidance;
  if (!facts || ["queued", "running"].includes(run.status)) return null;
  const canReview = hasRole(roles, "docai_reviewers");
  const canOperate = hasRole(roles, "docai_operators");
  if (run.failed_items > 0) {
    return {
      title: `${plural(run.failed_items, "document")} did not complete`,
      description: canOperate
        ? "Inspect the failure details below, then retry only the eligible failed documents."
        : "An operator can retry eligible failures after checking the details below.",
      label: "View failed documents",
      to: "#run-items",
    };
  }
  const reviewCount = facts.review.fields + facts.review.classifications;
  if (reviewCount > 0) {
    return {
      title: `${plural(reviewCount, "result")} ${reviewCount === 1 ? "needs" : "need"} human review`,
      description: canReview
        ? "Resolve the flagged results in their document context."
        : "A reviewer needs to resolve these results before delivery.",
      label: canReview ? "Review flagged results" : "View review queue",
      to: `/review?run=${run.id}`,
    };
  }
  if (facts.ground_truth.labels > 0 && facts.evaluations.count === 0 && canOperate) {
    return {
      title: "Ground truth is available",
      description: `${plural(facts.ground_truth.labels, "final label")} can be compared with this run without rerunning the model.`,
      label: "Evaluate this run",
      to: `/evaluation?run=${run.id}`,
    };
  }
  if (facts.evaluations.count > 0 && facts.export_ready) {
    return {
      title: "Evaluation is complete",
      description: "The stored results and evaluation context are ready to download.",
      label: "Export this run",
      to: `/exports?run=${run.id}`,
    };
  }
  if (facts.results > 0) {
    return {
      title: "Processing is complete",
      description: "Inspect values, confidence, validation, and grounding before exporting the result set.",
      label: "Inspect results",
      to: `/results?run=${run.id}`,
    };
  }
  return null;
}

export function nextResultsAction(run: Run, roles: string[]): JourneyAction | null {
  const facts = run.guidance;
  if (!facts) return null;
  const canReview = hasRole(roles, "docai_reviewers");
  const canOperate = hasRole(roles, "docai_operators");
  const reviewCount = facts.review.fields + facts.review.classifications;
  if (reviewCount > 0) {
    return {
      title: `${plural(reviewCount, "result")} still ${reviewCount === 1 ? "needs" : "need"} review`,
      description: "Resolve the flagged values before treating this result set as complete.",
      label: canReview ? "Continue review" : "View review queue",
      to: `/review?run=${run.id}`,
    };
  }
  if (facts.ground_truth.labels > 0 && facts.evaluations.count === 0 && canOperate) {
    return {
      title: "Results are ready to evaluate",
      description: `${plural(facts.ground_truth.labels, "final label")} can be compared with this run without another model call.`,
      label: "Evaluate run",
      to: `/evaluation?run=${run.id}`,
    };
  }
  if (facts.export_ready) {
    return {
      title: "Results are ready to share",
      description: "Export the stored values with the configuration snapshot and completed review history.",
      label: "Export this run",
      to: `/exports?run=${run.id}`,
    };
  }
  return null;
}
