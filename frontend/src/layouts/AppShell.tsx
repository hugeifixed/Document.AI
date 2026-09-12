/** §8 app shell: 260px sidebar (hideable on desktop; below lg — tablets portrait included — a <dialog> drawer with a real focus trap),
 *  header with project/dataset context, one <main>, skip link, live nav counts. */
import { Bars3Icon, ChevronDoubleLeftIcon, CircleStackIcon, FolderIcon, XMarkIcon } from "@heroicons/react/24/outline";
import { lazy, type ReactNode, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useSession } from "@/auth/Session";
import { AccountMenu } from "@/components/AccountMenu";
import { ErrorNotice } from "@/components/ErrorNotice";
import { ThemeToggle } from "@/components/ThemeToggle";
import { hasAcknowledgedProductTour } from "@/components/productTourStorage";
import { BrandMark, SelectControl } from "@/components/ui";
import {
  APP_NAVIGATION,
  canAccessNavigationItem,
  navigationSectionTourTarget,
  navigationTourTarget,
} from "@/navigation";
import { useJourneyDashboard } from "@/journey/guidance";
import { usePrefs } from "@/store/prefs";
import { useResolvedWorkingContext } from "@/workspace/context";

const LazyProductTour = lazy(() =>
  import("@/components/ProductTour").then((module) => ({ default: module.ProductTour })),
);

export function AppShell() {
  const { user } = useSession();
  const username = user?.username ?? "";
  const { sidebarHidden, setSidebarHidden } = usePrefs();
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);
  const [showTour, setShowTour] = useState(() => !!username && !hasAcknowledgedProductTour(username));
  const [tourKind, setTourKind] = useState<"overview" | "detailed">("overview");
  const startTour = useCallback(() => {
    setSidebarHidden(false);
    setMobileNavigationOpen(false);
    setTourKind("detailed");
    setShowTour(true);
  }, [setSidebarHidden]);
  const finishTour = useCallback(() => setShowTour(false), []);
  useEffect(() => {
    if (showTour) setSidebarHidden(false);
  }, [setSidebarHidden, showTour]);
  return (
    <>
      <AppShellContent
        startTour={startTour}
        sidebarHidden={sidebarHidden}
        setSidebarHidden={setSidebarHidden}
        mobileNavigationOpen={mobileNavigationOpen}
        setMobileNavigationOpen={setMobileNavigationOpen}
      />
      {showTour && (
        <Suspense fallback={null}>
          <LazyProductTour
            username={username}
            roles={user?.roles ?? []}
            kind={tourKind}
            onFinished={finishTour}
            onMobileNavigationChange={setMobileNavigationOpen}
          />
        </Suspense>
      )}
    </>
  );
}

export function WorkspaceContextBreadcrumb({ projectName, datasetName }: { projectName: string; datasetName: string }) {
  return (
    <nav
      className="breadcrumbs hidden min-w-0 flex-1 overflow-x-auto py-0 text-sm sm:block"
      aria-label="Working context"
    >
      <ul>
        <li>
          <Link
            to="/projects"
            className="min-w-0"
            aria-label={`Project: ${projectName}`}
            title={`Project: ${projectName}`}
          >
            <FolderIcon className="size-4 shrink-0 text-secondary" aria-hidden="true" />
            <span className="min-w-0">
              <span className="block text-xs leading-4 text-secondary">Project</span>
              <span className="block max-w-36 truncate font-medium leading-5 lg:max-w-56 xl:max-w-72">
                {projectName}
              </span>
            </span>
          </Link>
        </li>
        <li>
          <Link
            to="/datasets"
            className="min-w-0"
            aria-label={`Dataset: ${datasetName}`}
            title={`Dataset: ${datasetName}`}
          >
            <CircleStackIcon className="size-4 shrink-0 text-secondary" aria-hidden="true" />
            <span className="min-w-0">
              <span className="block text-xs leading-4 text-secondary">Dataset</span>
              <span className="block max-w-36 truncate font-medium leading-5 lg:max-w-56 xl:max-w-72">
                {datasetName}
              </span>
            </span>
          </Link>
        </li>
      </ul>
    </nav>
  );
}

/** Sidebar footer (§8.3): which adapters this deployment runs, straight from the session. */
function AdapterStatus({
  adapters,
  className = "",
}: {
  adapters: { layout: string; llm: string; task_runner: string };
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="flex items-center gap-2.5 rounded-box border border-base-300 bg-base-100 px-4 py-3 text-caption text-secondary">
        <span aria-hidden="true" className="inline-block size-2 shrink-0 rounded-full bg-success" />
        <span className="min-w-0">
          <span className="block">Adapters in use</span>
          <span
            className="block truncate font-mono text-(--color-ink-3)"
            title={`${adapters.layout} / ${adapters.llm} / ${adapters.task_runner}`}
          >
            {adapters.layout} / {adapters.llm}
          </span>
        </span>
      </div>
    </div>
  );
}

function AppShellContent({
  startTour,
  sidebarHidden,
  setSidebarHidden,
  mobileNavigationOpen,
  setMobileNavigationOpen,
}: {
  startTour: () => void;
  sidebarHidden: boolean;
  setSidebarHidden: (hidden: boolean) => void;
  mobileNavigationOpen: boolean;
  setMobileNavigationOpen: (open: boolean) => void;
}) {
  const { user, signOut } = useSession();
  const [signingOut, setSigningOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const { projectId, datasetId, project, dataset, projects, datasets, selectProject, selectDataset } =
    useResolvedWorkingContext();
  const dash = useJourneyDashboard(projectId, datasetId);
  const loc = useLocation();
  const drawer = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    setMobileNavigationOpen(false);
  }, [loc.pathname, setMobileNavigationOpen]);
  useLayoutEffect(() => {
    const dialog = drawer.current;
    if (!dialog) return;
    if (mobileNavigationOpen && !dialog.open) dialog.showModal();
    if (!mobileNavigationOpen && dialog.open) dialog.close();
  }, [mobileNavigationOpen]);
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 64rem)");
    const closeOnDesktop = () => {
      if (desktop.matches) setMobileNavigationOpen(false);
    };
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, [setMobileNavigationOpen]);
  const projectName =
    project?.name ?? (projectId ? (projects.isPending ? "Loading project…" : "Project unavailable") : "All projects");
  const datasetName =
    dataset?.name ?? (datasetId ? (datasets.isPending ? "Loading dataset…" : "Dataset unavailable") : "All datasets");
  const roles = user?.roles ?? [];
  async function logout() {
    setSigningOut(true);
    setLogoutError(null);
    try {
      await signOut();
    } catch {
      setLogoutError("We couldn’t log you out. Check your connection and try again.");
    } finally {
      setSigningOut(false);
    }
  }
  // Active item (DESIGN.md §8.2): brand-blue fill with white text; hovering it flips to a white surface with blue text.
  const navItemClass =
    "nav-item min-h-10 content-center whitespace-normal px-3 [overflow-wrap:anywhere] text-sm font-medium text-secondary focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2 aria-[current=page]:font-semibold";
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
        <label className="fieldset gap-1 p-0 text-sm">
          <span className="label text-secondary">Project</span>
          <SelectControl
            className="select-sm border-(--border-interactive)"
            aria-label="Active project"
            value={projectId ?? ""}
            onChange={(e) => selectProject(e.target.value || null)}
          >
            <option value="">All projects</option>
            {projects.data?.results.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </SelectControl>
        </label>
        <label className="fieldset gap-1 p-0 text-sm">
          <span className="label text-secondary">Dataset</span>
          <SelectControl
            className="select-sm border-(--border-interactive)"
            aria-label="Active dataset"
            value={datasetId ?? ""}
            disabled={!projectId}
            onChange={(e) => selectDataset(e.target.value || null)}
          >
            <option value="">{projectId ? "All datasets" : "Choose a project first"}</option>
            {datasets.data?.results.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </SelectControl>
        </label>
      </div>
    </div>
  );
  const nav = (tourId?: string, tourTargetPrefix?: string) => (
    <nav id={tourId} aria-label="Primary" className="space-y-1">
      {APP_NAVIGATION.map((section) => {
        const items = section.items.filter((item) => canAccessNavigationItem(item, roles));
        if (items.length === 0) return null;
        return (
          <section
            key={section.label}
            id={tourTargetPrefix ? navigationSectionTourTarget(tourTargetPrefix, section) : undefined}
            aria-label={section.label}
          >
            <h2 className="px-4 pt-2 text-caption font-semibold uppercase tracking-wide text-secondary">
              {section.label}
            </h2>
            <ul className="menu w-full gap-0.5 px-3 py-1 [--menu-active-bg:var(--color-primary)] [--menu-active-fg:var(--color-primary-content)]">
              {items.map((n) => (
                <li key={n.to}>
                  <NavLink
                    id={tourTargetPrefix ? navigationTourTarget(tourTargetPrefix, n) : undefined}
                    to={n.to}
                    end={n.to === "/"}
                    className={linkClass}
                  >
                    <n.icon className="size-5 shrink-0" aria-hidden="true" focusable="false" />
                    <span>{n.label}</span>
                    {n.count && dash.data && n.count(dash.data) > 0 && (
                      <span
                        className="nav-count badge badge-sm border-base-300 bg-base-200 tabular-nums"
                        aria-label={`${n.count(dash.data)} items`}
                      >
                        {n.count(dash.data)}
                      </span>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </nav>
  );
  return (
    <div className="min-h-screen bg-base-200">
      <a
        href="#main"
        className="absolute -top-16 left-2 z-50 rounded-field border border-base-300 bg-base-100 px-3 py-2 focus:top-2"
      >
        Skip to main content
      </a>
      <aside
        id="primary-sidebar"
        className={`fixed inset-y-0 left-0 hidden w-[16.25rem] flex-col overflow-y-auto border-r border-base-300 bg-base-200 py-4 ${sidebarHidden ? "" : "lg:flex"}`}
      >
        {contextPickers(
          "tour-working-context",
          <button
            type="button"
            className="btn btn-square btn-ghost btn-sm text-secondary"
            aria-label="Hide navigation"
            aria-controls="primary-sidebar"
            aria-expanded="true"
            onClick={() => setSidebarHidden(true)}
          >
            <ChevronDoubleLeftIcon className="size-5" aria-hidden="true" />
          </button>,
        )}
        {nav("tour-primary-navigation", "tour-nav")}
        {user && <AdapterStatus adapters={user.adapters} className="mt-auto px-3 pt-4" />}
      </aside>
      <dialog
        id="tour-navigation-dialog"
        ref={drawer}
        className="modal modal-start lg:hidden"
        onClose={() => setMobileNavigationOpen(false)}
        aria-label="Navigation"
      >
        <div className="modal-box h-full max-h-full w-[16.25rem] max-w-[calc(100vw-2rem)] rounded-none p-0 py-4">
          {contextPickers(
            "tour-mobile-working-context",
            <button
              type="button"
              className="btn btn-square btn-ghost btn-sm text-secondary"
              aria-label="Close navigation"
              onClick={() => setMobileNavigationOpen(false)}
            >
              <XMarkIcon className="size-5" aria-hidden="true" />
            </button>,
          )}
          {nav(undefined, "tour-mobile-nav")}
          {user && <AdapterStatus adapters={user.adapters} className="px-3 pt-4" />}
        </div>
        <form method="dialog" className="modal-backdrop">
          <button aria-label="Close navigation" tabIndex={-1}>
            Close
          </button>
        </form>
      </dialog>
      <div className={`min-h-screen bg-(--color-main) ${sidebarHidden ? "" : "lg:pl-[16.25rem]"}`}>
        <header className="sticky top-0 z-20 flex min-h-16 flex-wrap items-center gap-3 border-b border-base-300 bg-(--color-main) px-4 py-2 sm:px-6">
          <button
            id="tour-navigation-trigger"
            type="button"
            className="btn btn-square btn-ghost btn-sm lg:hidden"
            aria-label="Open navigation"
            onClick={() => setMobileNavigationOpen(true)}
          >
            <Bars3Icon className="size-5" aria-hidden />
          </button>
          {sidebarHidden && (
            <button
              type="button"
              className="btn btn-square btn-ghost btn-sm hidden lg:inline-flex"
              aria-label="Show navigation"
              aria-controls="primary-sidebar"
              aria-expanded="false"
              onClick={() => setSidebarHidden(false)}
            >
              <Bars3Icon className="size-5" aria-hidden />
            </button>
          )}
          <WorkspaceContextBreadcrumb projectName={projectName} datasetName={datasetName} />
          <div className="ml-auto flex min-w-0 items-center gap-1 text-sm">
            <ThemeToggle />
            <AccountMenu user={user} pending={signingOut} onLogout={logout} onStartTour={startTour} />
          </div>
        </header>
        <main id="main" className="mx-auto max-w-[1200px] p-4 sm:p-6 xl:p-8" tabIndex={-1}>
          {logoutError && (
            <div className="mb-6">
              <ErrorNotice message={logoutError} />
            </div>
          )}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
