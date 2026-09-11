/** §8 app shell: 260px sidebar (hideable on desktop; below lg — tablets portrait included — a <dialog> drawer with a real focus trap),
 *  header with project/dataset context, one <main>, skip link, live nav counts. */
import {
  AdjustmentsHorizontalIcon, ArrowDownTrayIcon, Bars3Icon, ChartBarIcon,
  ChevronDoubleLeftIcon, CircleStackIcon, ClipboardDocumentCheckIcon,
  DocumentMagnifyingGlassIcon, FolderIcon, PlayCircleIcon,
  ShareIcon, Squares2X2Icon, TagIcon, XMarkIcon,
} from "@heroicons/react/24/outline";
import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { get } from "@/api/client";
import { dashboardPollingInterval } from "@/api/polling";
import type { Dashboard, Dataset, Project } from "@/api/types";
import { useSession } from "@/auth/Session";
import { AccountMenu } from "@/components/AccountMenu";
import { ErrorNotice } from "@/components/ErrorNotice";
import { ThemeToggle } from "@/components/ThemeToggle";
import { hasAcknowledgedProductTour } from "@/components/productTourStorage";
import { BrandMark } from "@/components/ui";
import { usePrefs } from "@/store/prefs";

type NavItem = { to: string; label: string; icon: typeof Squares2X2Icon; count?: (d: Dashboard) => number; roles?: string[] };
const NAV: { label: string; items: NavItem[] }[] = [
  { label: "Workspace", items: [
    { to: "/", label: "Dashboard", icon: Squares2X2Icon },
    { to: "/projects", label: "Projects", icon: FolderIcon },
    { to: "/datasets", label: "Datasets & documents", icon: CircleStackIcon },
  ] },
  { label: "Configure", items: [
    { to: "/configurations", label: "Workflow versions", icon: AdjustmentsHorizontalIcon },
    { to: "/workflows/new", label: "New workflow version", icon: ShareIcon, roles: ["docai_operators"] },
  ] },
  { label: "Process", items: [
    { to: "/runs", label: "Runs", icon: PlayCircleIcon, count: (d) => d.runs?.running ?? 0 },
    { to: "/results", label: "Extracted results", icon: DocumentMagnifyingGlassIcon },
  ] },
  { label: "Review", items: [
    { to: "/review", label: "Review queue", icon: ClipboardDocumentCheckIcon, count: (d) => d.review_queue?.fields ?? 0, roles: ["docai_reviewers"] },
    { to: "/labeling", label: "Ground truth", icon: TagIcon, roles: ["docai_reviewers"] },
  ] },
  { label: "Measure & share", items: [
    { to: "/evaluation", label: "Evaluations", icon: ChartBarIcon },
    { to: "/exports", label: "Exports", icon: ArrowDownTrayIcon },
  ] },
];

const LazyProductTour = lazy(() => import("@/components/ProductTour").then((module) => ({ default: module.ProductTour })));

export function AppShell() {
  const { user } = useSession();
  const username = user?.username ?? "";
  const [showTour, setShowTour] = useState(() => !!username && !hasAcknowledgedProductTour(username));
  const startTour = useCallback(() => setShowTour(true), []);
  const finishTour = useCallback(() => setShowTour(false), []);
  return <>
    <AppShellContent startTour={startTour} />
    {showTour && <Suspense fallback={null}><LazyProductTour username={username} onFinished={finishTour} /></Suspense>}
  </>;
}

export function WorkspaceContextBreadcrumb({ projectName, datasetName }: {
  projectName: string;
  datasetName: string;
}) {
  return (
    <nav className="breadcrumbs hidden min-w-0 flex-1 overflow-x-auto py-0 text-sm sm:block" aria-label="Working context">
      <ul>
        <li>
          <Link to="/projects" className="min-w-0" aria-label={`Project: ${projectName}`} title={`Project: ${projectName}`}>
            <FolderIcon className="size-4 shrink-0 text-secondary" aria-hidden="true" />
            <span className="min-w-0">
              <span className="block text-xs leading-4 text-secondary">Project</span>
              <span className="block max-w-36 truncate font-medium leading-5 lg:max-w-56 xl:max-w-72">{projectName}</span>
            </span>
          </Link>
        </li>
        <li>
          <Link to="/datasets" className="min-w-0" aria-label={`Dataset: ${datasetName}`} title={`Dataset: ${datasetName}`}>
            <CircleStackIcon className="size-4 shrink-0 text-secondary" aria-hidden="true" />
            <span className="min-w-0">
              <span className="block text-xs leading-4 text-secondary">Dataset</span>
              <span className="block max-w-36 truncate font-medium leading-5 lg:max-w-56 xl:max-w-72">{datasetName}</span>
            </span>
          </Link>
        </li>
      </ul>
    </nav>
  );
}

/** Sidebar footer (§8.3): which adapters this deployment runs, straight from the session. */
function AdapterStatus({ adapters, className = "" }: { adapters: { layout: string; llm: string; task_runner: string }; className?: string }) {
  return (
    <div className={className}>
      <div className="flex items-center gap-2.5 rounded-box border border-base-300 bg-base-100 px-4 py-3 text-caption text-secondary">
        <span aria-hidden="true" className="inline-block size-2 shrink-0 rounded-full bg-success" />
        <span className="min-w-0"><span className="block">Adapters in use</span><span className="block truncate font-mono text-(--color-ink-3)" title={`${adapters.layout} / ${adapters.llm} / ${adapters.task_runner}`}>{adapters.layout} / {adapters.llm}</span></span>
      </div>
    </div>
  );
}

function AppShellContent({ startTour }: { startTour: () => void }) {
  const { user, signOut } = useSession();
  const [signingOut, setSigningOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const { projectId, datasetId, sidebarHidden, setSidebarHidden, setContext } = usePrefs();
  const dash = useQuery({ queryKey: ["dashboard", projectId], queryFn: ({ signal }) => get<Dashboard>("/dashboard/", projectId ? { project: projectId } : undefined, { signal }), refetchInterval: (query) => dashboardPollingInterval(query.state.data) });
  const projects = useQuery({ queryKey: ["projects", "all"], queryFn: ({ signal }) => get<{ results: Project[] }>("/projects/", { page_size: 200 }, { signal }) });
  const datasets = useQuery({ queryKey: ["datasets", projectId], enabled: !!projectId, queryFn: ({ signal }) => get<{ results: Dataset[] }>("/datasets/", { page_size: 200, project: projectId }, { signal }) });
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  const drawer = useRef<HTMLDialogElement>(null);
  useEffect(() => { setOpen(false); }, [loc.pathname]);
  useEffect(() => { const d = drawer.current; if (!d) return; if (open && !d.open) d.showModal(); if (!open && d.open) d.close(); }, [open]);
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 64rem)");
    const closeOnDesktop = () => { if (desktop.matches) setOpen(false); };
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);
  useEffect(() => {
    if (projects.isSuccess && projectId && !projects.data.results.some((project) => project.id === projectId)) setContext(null, null);
  }, [projectId, projects.data, projects.isSuccess, setContext]);
  useEffect(() => {
    if (datasets.isSuccess && projectId && datasetId && !datasets.data.results.some((dataset) => dataset.id === datasetId)) setContext(projectId, null);
  }, [datasetId, datasets.data, datasets.isSuccess, projectId, setContext]);
  const project = projects.data?.results.find((p) => p.id === projectId);
  const dataset = datasets.data?.results.find((d) => d.id === datasetId);
  const projectName = project?.name ?? (projectId ? (projects.isPending ? "Loading project…" : "Project unavailable") : "All projects");
  const datasetName = dataset?.name ?? (datasetId ? (datasets.isPending ? "Loading dataset…" : "Dataset unavailable") : "All datasets");
  const canSee = (item: NavItem) => !item.roles || item.roles.some((role) => user?.roles.includes(role));
  async function logout() {
    setSigningOut(true);
    setLogoutError(null);
    try { await signOut(); }
    catch { setLogoutError("We couldn’t log you out. Check your connection and try again."); }
    finally { setSigningOut(false); }
  }
  // Active item (DESIGN.md §8.2): brand-blue fill with white text; hovering it flips to a white surface with blue text.
  const navItemClass = "nav-item min-h-10 content-center whitespace-normal px-3 [overflow-wrap:anywhere] text-sm font-medium text-secondary focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2 aria-[current=page]:font-semibold";
  const linkClass = ({ isActive }: { isActive: boolean }) => `${navItemClass}${isActive ? " menu-active" : ""}`;
  const contextPickers = (tourId?: string, control?: ReactNode) => (
    <div id={tourId} className="mb-2 px-3">
      <div className="mb-4 flex min-h-8 items-center gap-2.5 ps-1">
        <BrandMark size={30} />
        <span className="font-semibold tracking-tight">DocAI</span>
        {control && <span className="ms-auto flex items-center">{control}</span>}
      </div>
      <div className="elevation-raised space-y-3 rounded-box border border-base-300 bg-base-100 p-4">
        <p className="text-caption font-semibold uppercase tracking-wide text-(--color-ink-3)">Working context</p>
        <label className="fieldset gap-1 p-0 text-sm"><span className="label text-secondary">Project</span>
          <select className="select select-sm w-full border-(--border-interactive)" aria-label="Active project" value={projectId ?? ""} onChange={(e) => usePrefs.getState().setContext(e.target.value || null, null)}>
            <option value="">All projects</option>{projects.data?.results.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label className="fieldset gap-1 p-0 text-sm"><span className="label text-secondary">Dataset</span>
          <select className="select select-sm w-full border-(--border-interactive)" aria-label="Active dataset" value={datasetId ?? ""} disabled={!projectId} onChange={(e) => usePrefs.getState().setContext(projectId, e.target.value || null)}>
            <option value="">{projectId ? "All datasets" : "Choose a project first"}</option>{datasets.data?.results.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </label>
      </div>
    </div>
  );
  const nav = (tourId?: string) => (
    <nav id={tourId} aria-label="Primary" className="space-y-1">
      {NAV.map((section) => {
        const items = section.items.filter(canSee);
        if (items.length === 0) return null;
        return <section key={section.label} aria-label={section.label}>
          <h2 className="px-4 pt-2 text-caption font-semibold uppercase tracking-wide text-(--color-ink-3)">{section.label}</h2>
          <ul className="menu w-full gap-0.5 px-3 py-1 [--menu-active-bg:var(--color-primary)] [--menu-active-fg:var(--color-primary-content)]">
            {items.map((n) => <li key={n.to}>
              <NavLink to={n.to} end={n.to === "/"} className={linkClass}>
                <n.icon className="size-5 shrink-0" aria-hidden="true" focusable="false" />
                <span>{n.label}</span>
                {n.count && dash.data && n.count(dash.data) > 0 && <span className="nav-count badge badge-sm border-base-300 bg-base-200 tabular-nums" aria-label={`${n.count(dash.data)} items`}>{n.count(dash.data)}</span>}
              </NavLink>
            </li>)}
          </ul>
        </section>;
      })}
    </nav>
  );
  return (
    <div className="min-h-screen bg-base-200">
      <a href="#main" className="absolute -top-16 left-2 z-50 rounded-field border border-base-300 bg-base-100 px-3 py-2 focus:top-2">Skip to main content</a>
      <aside id="primary-sidebar" className={`fixed inset-y-0 left-0 hidden w-[16.25rem] flex-col overflow-y-auto border-r border-base-300 bg-base-200 py-4 ${sidebarHidden ? "" : "lg:flex"}`}>
        {contextPickers("tour-working-context", (
          <button type="button" className="btn btn-square btn-ghost btn-sm text-secondary" aria-label="Hide navigation" aria-controls="primary-sidebar" aria-expanded="true" onClick={() => setSidebarHidden(true)}>
            <ChevronDoubleLeftIcon className="size-5" aria-hidden="true" />
          </button>
        ))}
        {nav("tour-primary-navigation")}
        {user && <AdapterStatus adapters={user.adapters} className="mt-auto px-3 pt-4" />}
      </aside>
      <dialog ref={drawer} className="modal modal-start lg:hidden" onClose={() => setOpen(false)} aria-label="Navigation">
        <div className="modal-box h-full max-h-full w-[16.25rem] max-w-[calc(100vw-2rem)] rounded-none p-0 py-4">
          {contextPickers(undefined, (
            <button type="button" className="btn btn-square btn-ghost btn-sm text-secondary" aria-label="Close navigation" onClick={() => setOpen(false)}>
              <XMarkIcon className="size-5" aria-hidden="true" />
            </button>
          ))}
          {nav()}
          {user && <AdapterStatus adapters={user.adapters} className="px-3 pt-4" />}
        </div>
        <form method="dialog" className="modal-backdrop"><button aria-label="Close navigation" tabIndex={-1}>Close</button></form>
      </dialog>
      <div className={`min-h-screen bg-(--color-main) ${sidebarHidden ? "" : "lg:pl-[16.25rem]"}`}>
        <header className="sticky top-0 z-20 flex min-h-16 flex-wrap items-center gap-3 border-b border-base-300 bg-(--color-main) px-4 py-2 sm:px-6">
          <button id="tour-navigation-trigger" type="button" className="btn btn-square btn-ghost btn-sm lg:hidden" aria-label="Open navigation" onClick={() => setOpen(true)}><Bars3Icon className="size-5" aria-hidden /></button>
          {sidebarHidden && <button type="button" className="btn btn-square btn-ghost btn-sm hidden lg:inline-flex" aria-label="Show navigation" aria-controls="primary-sidebar" aria-expanded="false" onClick={() => setSidebarHidden(false)}><Bars3Icon className="size-5" aria-hidden /></button>}
          <WorkspaceContextBreadcrumb projectName={projectName} datasetName={datasetName} />
          <div className="ml-auto flex min-w-0 items-center gap-1 text-sm">
            <ThemeToggle />
            <AccountMenu user={user} pending={signingOut} onLogout={logout} onStartTour={startTour} />
          </div>
        </header>
        <main id="main" className="mx-auto max-w-[1200px] p-4 sm:p-6 xl:p-8" tabIndex={-1}>
          {logoutError && <div className="mb-6"><ErrorNotice message={logoutError} /></div>}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
