/** §8 app shell: 260px sidebar (collapses below md into a <dialog> drawer with a real focus trap),
 *  header with project/dataset context, one <main>, skip link, live nav counts. */
import {
  AdjustmentsHorizontalIcon, ArrowDownTrayIcon, Bars3Icon, ChartBarIcon,
  CircleStackIcon, ClipboardDocumentCheckIcon,
  DocumentMagnifyingGlassIcon, FolderIcon, PlayCircleIcon,
  ShareIcon, Squares2X2Icon, TagIcon,
} from "@heroicons/react/24/outline";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { get } from "@/api/client";
import type { Dashboard, Dataset, Project } from "@/api/types";
import { useSession } from "@/auth/Session";
import { AccountMenu } from "@/components/AccountMenu";
import { ErrorNotice } from "@/components/ErrorNotice";
import { ProductTour } from "@/components/ProductTour";
import { ThemeToggle } from "@/components/ThemeToggle";
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

export function AppShell() {
  const { user } = useSession();
  return <ProductTour username={user?.username ?? ""}>{(startTour) => <AppShellContent startTour={startTour} />}</ProductTour>;
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

function AppShellContent({ startTour }: { startTour: () => void }) {
  const { user, signOut } = useSession();
  const [signingOut, setSigningOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const { projectId, datasetId } = usePrefs();
  const dash = useQuery({ queryKey: ["dashboard", projectId], queryFn: () => get<Dashboard>("/dashboard/", projectId ? { project: projectId } : undefined), refetchInterval: 15000 });
  const projects = useQuery({ queryKey: ["projects", "all"], queryFn: () => get<{ results: Project[] }>("/projects/", { page_size: 200 }) });
  const datasets = useQuery({ queryKey: ["datasets", projectId], enabled: !!projectId, queryFn: () => get<{ results: Dataset[] }>("/datasets/", { page_size: 200, project: projectId }) });
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  const drawer = useRef<HTMLDialogElement>(null);
  useEffect(() => { setOpen(false); }, [loc.pathname]);
  useEffect(() => { const d = drawer.current; if (!d) return; if (open && !d.open) d.showModal(); if (!open && d.open) d.close(); }, [open]);
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 48rem)");
    const closeOnDesktop = () => { if (desktop.matches) setOpen(false); };
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);
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
  const navItemClass = "min-h-10 whitespace-normal [overflow-wrap:anywhere] border-s-[3px] border-transparent text-base text-secondary focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2 aria-[current=page]:border-accent aria-[current=page]:font-semibold";
  const linkClass = ({ isActive }: { isActive: boolean }) => `${navItemClass}${isActive ? " menu-active" : ""}`;
  const contextPickers = (tourId?: string) => (
    <div id={tourId} className="mb-3 space-y-3 px-4">
      <div className="mb-4 flex items-center gap-2"><span aria-hidden className="inline-block size-6 rounded bg-accent" /><span className="font-semibold">DocAI</span></div>
      <p className="text-caption font-semibold uppercase tracking-wide text-secondary">Working context</p>
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
  );
  const nav = (tourId?: string) => (
    <nav id={tourId} aria-label="Primary" className="space-y-1">
      {NAV.map((section) => {
        const items = section.items.filter(canSee);
        if (items.length === 0) return null;
        return <section key={section.label} aria-label={section.label}>
          <h2 className="px-4 pt-2 text-caption font-semibold uppercase tracking-wide text-secondary">{section.label}</h2>
          <ul className="menu w-full gap-0.5 py-1 [--menu-active-bg:var(--color-base-300)] [--menu-active-fg:var(--color-base-content)]">
            {items.map((n) => <li key={n.to}>
              <NavLink to={n.to} end={n.to === "/"} className={linkClass}>
                <n.icon className="size-5 shrink-0" aria-hidden="true" focusable="false" />
                <span>{n.label}</span>
                {n.count && dash.data && n.count(dash.data) > 0 && <span className="badge badge-sm badge-outline tabular-nums" aria-label={`${n.count(dash.data)} items`}>{n.count(dash.data)}</span>}
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
      <aside className="fixed inset-y-0 left-0 hidden w-[16.25rem] overflow-y-auto border-r border-base-300 bg-base-200 py-4 md:block">
        {contextPickers("tour-working-context")}{nav("tour-primary-navigation")}
      </aside>
      <dialog ref={drawer} className="modal modal-start md:hidden" onClose={() => setOpen(false)} aria-label="Navigation">
        <div className="modal-box h-full max-h-full w-[16.25rem] max-w-[calc(100vw-2rem)] rounded-none p-0 py-2">
          <form method="dialog" className="px-2"><button className="btn btn-sm btn-ghost mb-2">Close</button></form>
          {contextPickers()}{nav()}
        </div>
        <form method="dialog" className="modal-backdrop"><button aria-label="Close navigation" tabIndex={-1}>Close</button></form>
      </dialog>
      <div className="md:pl-[16.25rem]">
        <header className="sticky top-0 z-20 flex min-h-14 flex-wrap items-center gap-3 py-2 border-b bg-base-100 px-4 border-base-300">
          <button id="tour-navigation-trigger" type="button" className="btn btn-ghost btn-sm md:hidden" aria-label="Open navigation" onClick={() => setOpen(true)}><Bars3Icon className="size-5" aria-hidden /></button>
          <WorkspaceContextBreadcrumb projectName={projectName} datasetName={datasetName} />
          <div className="ml-auto flex min-w-0 items-center gap-1 text-sm">
            <ThemeToggle />
            <AccountMenu user={user} pending={signingOut} onLogout={logout} onStartTour={startTour} />
          </div>
        </header>
        <main id="main" className="mx-auto max-w-[1200px] p-6" tabIndex={-1}>
          {logoutError && <div className="mb-4"><ErrorNotice message={logoutError} /></div>}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
