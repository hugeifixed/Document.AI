import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { matchPath, useLocation, useNavigate } from "react-router-dom";
import type { Document, Run } from "@/common/types/api";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useAuthorizedDataset, useWorkingContext } from "./context";

type Scope = { projectId: string | null; datasetId: string | null };
type Draft = { dirty: boolean; saving: boolean };
type Transition = { scope: Scope; locationKey: string; destination: string };

export function isDocumentWorkspace(pathname: string) {
  return ["/documents/:id", "/review/:id", "/labeling/:id"].some((pattern) => matchPath(pattern, pathname));
}

/** Resource and pagination parameters belong to the old scope; independent list filters survive. */
export function workspaceDestination(pathname: string, search: string) {
  const target = isDocumentWorkspace(pathname)
    ? "/datasets"
    : matchPath("/runs/:id", pathname)
      ? "/runs"
      : matchPath("/workflows/new", pathname)
        ? "/configurations"
        : pathname;
  const params = new URLSearchParams(target === pathname ? search : "");
  for (const name of [
    "project",
    "dataset",
    "document",
    "document_id",
    "document_ids",
    "run",
    "workflow",
    "field",
    "category",
    "schema",
    "prompt",
    "evaluation",
    "created",
    "from",
    "page",
    "offset",
    "cursor",
  ]) {
    params.delete(name);
  }
  const query = params.toString();
  return target + (query ? `?${query}` : "");
}

export function workspaceChangeHint(pathname: string) {
  if (isDocumentWorkspace(pathname)) return "Changing workspace opens its documents.";
  if (matchPath("/runs/:id", pathname)) return "Changing workspace opens its runs.";
  if (matchPath("/workflows/new", pathname)) return "Changing workspace opens its workflow versions.";
  return undefined;
}

interface WorkspaceNavigation {
  saving: boolean;
  changeProject: (projectId: string | null) => void;
  changeDataset: (datasetId: string | null) => void;
  registerDraft: (id: symbol, draft: Draft | null) => void;
  alignScope: (scope: Scope, locationKey: string) => boolean;
  canRepair: () => boolean;
}
const NavigationContext = createContext<WorkspaceNavigation | null>(null);

export function WorkspaceNavigationProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const currentLocation = useRef(location);
  const suppressedLocation = useRef<string | null>(null);
  const drafts = useRef(new Map<symbol, Draft>());
  const [draftState, setDraftState] = useState<Draft>({ dirty: false, saving: false });
  const { saving } = draftState;
  const [pending, setPending] = useState<Transition | null>(null);
  const pendingRef = useRef<Transition | null>(null);
  useLayoutEffect(() => {
    currentLocation.current = location;
    if (suppressedLocation.current !== location.key) suppressedLocation.current = null;
    if (pendingRef.current && pendingRef.current.locationKey !== location.key) {
      pendingRef.current = null;
      setPending(null);
    }
  }, [location]);
  const registerDraft = useCallback((id: symbol, draft: Draft | null) => {
    if (draft) drafts.current.set(id, draft);
    else drafts.current.delete(id);
    const values = [...drafts.current.values()];
    const next = { dirty: values.some((value) => value.dirty), saving: values.some((value) => value.saving) };
    setDraftState((current) => (current.dirty === next.dirty && current.saving === next.saving ? current : next));
  }, []);
  const close = useCallback(() => {
    pendingRef.current = null;
    setPending(null);
  }, []);
  const commit = (transition: Transition) => {
    if (
      transition.locationKey !== currentLocation.current.key ||
      [...drafts.current.values()].some((draft) => draft.saving)
    )
      return;
    // Reject late resource effects from the departing URL before changing either state.
    suppressedLocation.current = transition.locationKey;
    close();
    useWorkingContext.setState(transition.scope);
    void navigate(transition.destination);
  };
  const request = (scope: Scope) => {
    const current = useWorkingContext.getState();
    if (
      (scope.projectId === current.projectId && scope.datasetId === current.datasetId) ||
      [...drafts.current.values()].some((draft) => draft.saving)
    )
      return;
    const source = currentLocation.current;
    const transition = {
      scope,
      locationKey: source.key,
      destination: workspaceDestination(source.pathname, source.search),
    };
    if ([...drafts.current.values()].some((draft) => draft.dirty)) {
      pendingRef.current = transition;
      setPending(transition);
    } else commit(transition);
  };
  const alignScope = useCallback((scope: Scope, locationKey: string) => {
    if (
      locationKey !== currentLocation.current.key ||
      suppressedLocation.current === locationKey ||
      pendingRef.current ||
      [...drafts.current.values()].some((draft) => draft.saving)
    )
      return false;
    const current = useWorkingContext.getState();
    if (current.projectId !== scope.projectId || current.datasetId !== scope.datasetId) {
      useWorkingContext.setState(scope);
    }
    return true;
  }, []);
  const canRepair = useCallback(
    () =>
      !pending &&
      !pendingRef.current &&
      !draftState.dirty &&
      !draftState.saving &&
      ![...drafts.current.values()].some((draft) => draft.dirty || draft.saving),
    [draftState, pending],
  );
  return (
    <NavigationContext.Provider
      value={{
        saving,
        registerDraft,
        alignScope,
        canRepair,
        changeProject: (projectId) => {
          if (projectId !== useWorkingContext.getState().projectId) request({ projectId, datasetId: null });
        },
        changeDataset: (datasetId) => {
          const projectId = useWorkingContext.getState().projectId;
          request({ projectId, datasetId: projectId ? datasetId : null });
        },
      }}
    >
      {children}
      <ConfirmDialog
        open={!!pending && pending.locationKey === location.key}
        title="Discard unsaved changes?"
        summary="Your unsaved changes will be discarded when you change workspace."
        confirmLabel="Discard and switch"
        pending={saving}
        onClose={close}
        onConfirm={() => {
          if (pending) commit(pending);
        }}
      />
    </NavigationContext.Provider>
  );
}

export function useWorkspaceNavigation() {
  const context = useContext(NavigationContext);
  if (!context) throw new Error("WorkspaceNavigationProvider is required");
  return context;
}

/** Transient registration: isolated forms remain usable without the shell. */
export function useWorkspaceDraft(dirty: boolean, saving = false): void {
  const register = useContext(NavigationContext)?.registerDraft;
  const id = useRef(Symbol("workspace draft"));
  useLayoutEffect(() => {
    register?.(id.current, { dirty, saving });
  }, [register, dirty, saving]);
  useLayoutEffect(() => {
    const key = id.current;
    return () => register?.(key, null);
  }, [register]);
}

/** Align once per opened resource, never from a refetch after a user has switched scope. */
function useResourceScope(projectId: string | undefined, datasetId: string | undefined, resourceKey: string) {
  const context = useContext(NavigationContext);
  const { key } = useLocation();
  const aligned = useRef<string | null>(null);
  const align = context?.alignScope;
  useEffect(() => {
    if (projectId && datasetId && aligned.current !== resourceKey && align?.({ projectId, datasetId }, key)) {
      aligned.current = resourceKey;
    }
  }, [align, projectId, datasetId, resourceKey, key]);
}

export function useDocumentWorkspaceScope(document: Document | undefined) {
  const navigation = useContext(NavigationContext);
  const dataset = useAuthorizedDataset(document?.dataset, !!navigation && !!document);
  const authorized = dataset.isSuccess && !dataset.isStale && dataset.data.id === document?.dataset;
  useResourceScope(
    authorized ? dataset.data.project : undefined,
    authorized ? dataset.data.id : undefined,
    `document:${document?.id ?? ""}`,
  );
}

export function useRunWorkspaceScope(run: Run | undefined) {
  useResourceScope(run?.project, run?.dataset, `run:${run?.id ?? ""}`);
}
