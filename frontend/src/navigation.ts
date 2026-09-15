import {
  AdjustmentsHorizontalIcon,
  ArrowDownTrayIcon,
  ChartBarIcon,
  CircleStackIcon,
  ClipboardDocumentCheckIcon,
  DocumentMagnifyingGlassIcon,
  FolderIcon,
  PlayCircleIcon,
  ShareIcon,
  Squares2X2Icon,
  TagIcon,
} from "@heroicons/react/24/outline";
import type { Dashboard } from "@/common/types/api";

export type NavigationItem = {
  to: string;
  label: string;
  tourId: string;
  tourDescription: string;
  icon: typeof Squares2X2Icon;
  count?: (dashboard: Dashboard) => number;
  roles?: string[];
};

export type NavigationSection = {
  label: string;
  tourId: string;
  items: NavigationItem[];
};

export const APP_NAVIGATION: NavigationSection[] = [
  {
    label: "Workspace",
    tourId: "workspace",
    items: [
      {
        to: "/",
        label: "Dashboard",
        tourId: "dashboard",
        tourDescription:
          "See the selected project's activity, work in progress, review backlog, recent runs, and failures that need attention.",
        icon: Squares2X2Icon,
      },
      {
        to: "/projects",
        label: "Projects",
        tourId: "projects",
        tourDescription:
          "Create and select a business workspace. Each project keeps its datasets, workflow versions, runs, and results together.",
        icon: FolderIcon,
      },
      {
        to: "/datasets",
        label: "Datasets & documents",
        tourId: "datasets",
        tourDescription:
          "Create a dataset, upload source documents, and check validation or processing failures. Uploads belong only to the selected dataset.",
        icon: CircleStackIcon,
      },
    ],
  },
  {
    label: "Configure",
    tourId: "configure",
    items: [
      {
        to: "/configurations",
        label: "Workflow versions",
        tourId: "workflow-versions",
        tourDescription:
          "Review saved workflow definitions, versions, and approval status. Approved versions are available when starting a run.",
        icon: AdjustmentsHorizontalIcon,
      },
      {
        to: "/workflows/new",
        label: "New workflow version",
        tourId: "new-workflow-version",
        tourDescription:
          "Define classification, extraction, or document-splitting behavior, validate the configuration, and save a new version for approval.",
        icon: ShareIcon,
        roles: ["docai_operators"],
      },
    ],
  },
  {
    label: "Process",
    tourId: "process",
    items: [
      {
        to: "/runs",
        label: "Runs",
        tourId: "runs",
        tourDescription:
          "Start an approved workflow against the selected dataset, monitor document progress, and cancel or retry work when needed.",
        icon: PlayCircleIcon,
        count: (dashboard) => dashboard.runs?.running ?? 0,
      },
      {
        to: "/results",
        label: "Extracted results",
        tourId: "results",
        tourDescription:
          "Search model output and inspect confidence, validation, and review status before sending exceptions for review or exporting data.",
        icon: DocumentMagnifyingGlassIcon,
      },
    ],
  },
  {
    label: "Review",
    tourId: "review",
    items: [
      {
        to: "/review",
        label: "Review queue",
        tourId: "review-queue",
        tourDescription:
          "Resolve extracted fields and document classifications that need human judgment, with every decision recorded.",
        icon: ClipboardDocumentCheckIcon,
        count: (dashboard) => (dashboard.review_queue?.fields ?? 0) + (dashboard.review_queue?.classifications ?? 0),
        roles: ["docai_reviewers"],
      },
      {
        to: "/labeling",
        label: "Ground truth",
        tourId: "ground-truth",
        tourDescription:
          "Create final human labels from document text, regions, or spreadsheet cells. Evaluations use these labels as the expected answer.",
        icon: TagIcon,
        roles: ["docai_reviewers"],
      },
    ],
  },
  {
    label: "Measure & share",
    tourId: "measure-share",
    items: [
      {
        to: "/evaluation",
        label: "Evaluations",
        tourId: "evaluations",
        tourDescription:
          "Compare a completed run with final ground truth and inspect extraction, classification, and segmentation quality metrics.",
        icon: ChartBarIcon,
      },
      {
        to: "/exports",
        label: "Exports",
        tourId: "exports",
        tourDescription:
          "Download completed run data as JSON, CSV, or XLSX, including the configuration snapshot and review history where applicable.",
        icon: ArrowDownTrayIcon,
      },
    ],
  },
];

export function canAccessNavigationItem(item: NavigationItem, roles: string[]) {
  return !item.roles || item.roles.some((role) => roles.includes(role));
}

export function visibleNavigationItems(roles: string[]) {
  return APP_NAVIGATION.flatMap((section) => section.items.filter((item) => canAccessNavigationItem(item, roles)));
}

export function navigationTourTarget(prefix: string, item: NavigationItem) {
  return `${prefix}-${item.tourId}`;
}

export function navigationSectionTourTarget(prefix: string, section: NavigationSection) {
  return `${prefix}-section-${section.tourId}`;
}
