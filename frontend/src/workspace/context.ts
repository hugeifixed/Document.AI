import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useEffect } from "react";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { ApiError, get } from "@/common/api/client";
import type { Dataset, Project } from "@/common/types/api";

interface WorkingContextState {
  projectId: string | null;
  datasetId: string | null;
  selectProject: (projectId: string | null) => void;
  selectDataset: (datasetId: string | null) => void;
  selectDatasetForProject: (projectId: string, datasetId: string) => void;
  clear: () => void;
}

/** Persisted Project/Dataset scope. Transitions keep a Dataset nested under a Project. */
export const useWorkingContext = create<WorkingContextState>()(
  persist(
    (set) => ({
      projectId: null,
      datasetId: null,
      selectProject: (projectId) =>
        set((current) =>
          current.projectId === projectId && (projectId !== null || current.datasetId === null)
            ? current
            : { projectId, datasetId: null },
        ),
      selectDataset: (datasetId) => set((current) => ({ datasetId: current.projectId ? datasetId : null })),
      selectDatasetForProject: (projectId, datasetId) => set({ projectId, datasetId }),
      clear: () => set({ projectId: null, datasetId: null }),
    }),
    {
      name: "docai-working-context",
      partialize: ({ projectId, datasetId }) => ({ projectId, datasetId }),
      merge: (persisted, current) => {
        const saved = persisted as Partial<WorkingContextState>;
        const projectId = typeof saved.projectId === "string" ? saved.projectId : null;
        const datasetId = projectId && typeof saved.datasetId === "string" ? saved.datasetId : null;
        return { ...current, projectId, datasetId };
      },
    },
  ),
);

export function clearWorkingContext() {
  useWorkingContext.getState().clear();
}

/** Cached success alone does not authorize a scope change while its stale GET is being refreshed. */
export function authorizedQueryData<T>(
  query: Pick<UseQueryResult<T>, "data" | "isSuccess" | "isStale" | "isFetchedAfterMount" | "isFetching">,
) {
  return query.isSuccess && (!query.isStale || (query.isFetchedAfterMount && !query.isFetching))
    ? query.data
    : undefined;
}

/** Preserve authorized metadata timestamps so stale entries refetch before scope alignment. */
export function useAuthorizedDataset(datasetId: string | null | undefined, enabled = true) {
  const client = useQueryClient();
  const cached = client
    .getQueryCache()
    .findAll({ queryKey: ["datasets"] })
    .filter((query) => query.state.status === "success" && !query.state.isInvalidated)
    .sort((left, right) => right.state.dataUpdatedAt - left.state.dataUpdatedAt)
    .map((query) => ({
      dataset: (query.state.data as { results?: Dataset[] } | undefined)?.results?.find(
        (item) => item.id === datasetId,
      ),
      updatedAt: query.state.dataUpdatedAt,
    }))
    .find((candidate) => candidate.dataset);
  return useQuery({
    queryKey: ["dataset", datasetId],
    enabled: enabled && !!datasetId,
    queryFn: ({ signal }) => get<Dataset>(`/datasets/${datasetId}/`, undefined, { signal }),
    initialData: cached?.dataset,
    initialDataUpdatedAt: cached?.updatedAt,
    staleTime: 10_000,
  });
}

/** Resolve selected identifiers independently of the first page of selector options. */
export function useResolvedWorkingContext(canRepair: () => boolean) {
  const context = useWorkingContext();
  const projects = useQuery({
    queryKey: ["projects", "all"],
    queryFn: ({ signal }) => get<{ results: Project[] }>("/projects/", { page_size: 200 }, { signal }),
  });
  const datasets = useQuery({
    queryKey: ["datasets", context.projectId],
    enabled: !!context.projectId,
    queryFn: ({ signal }) =>
      get<{ results: Dataset[] }>("/datasets/", { page_size: 200, project: context.projectId }, { signal }),
  });
  const listedProject = projects.isSuccess
    ? projects.data.results.find((candidate) => candidate.id === context.projectId)
    : undefined;
  const listedDataset = datasets.isSuccess
    ? datasets.data.results.find((candidate) => candidate.id === context.datasetId)
    : undefined;
  const selectedProject = useQuery({
    queryKey: ["project", context.projectId],
    enabled: !!context.projectId && projects.isSuccess && !listedProject,
    queryFn: ({ signal }) => get<Project>(`/projects/${context.projectId}/`, undefined, { signal }),
  });
  const selectedDataset = useAuthorizedDataset(context.datasetId, datasets.isSuccess && !listedDataset);
  const project = listedProject ?? (selectedProject.isSuccess ? selectedProject.data : undefined);
  const candidateDataset = listedDataset ?? (selectedDataset.isSuccess ? selectedDataset.data : undefined);
  const dataset = candidateDataset?.project === context.projectId ? candidateDataset : undefined;
  const missingProject =
    !listedProject &&
    selectedProject.isFetchedAfterMount &&
    !selectedProject.isFetching &&
    selectedProject.isError &&
    selectedProject.error instanceof ApiError &&
    selectedProject.error.status === 404;
  const missingDataset =
    !listedDataset &&
    selectedDataset.isFetchedAfterMount &&
    !selectedDataset.isFetching &&
    selectedDataset.isError &&
    selectedDataset.error instanceof ApiError &&
    selectedDataset.error.status === 404;
  const authorizedDataset =
    authorizedQueryData(datasets)?.results.find((item) => item.id === context.datasetId) ??
    (!listedDataset ? authorizedQueryData(selectedDataset) : undefined);
  const mismatchedDataset =
    authorizedDataset?.id === context.datasetId && authorizedDataset.project !== context.projectId;

  useEffect(() => {
    if (!canRepair() || (!missingProject && !missingDataset && !mismatchedDataset)) return;
    // An old response must never repair the scope selected since that request started.
    useWorkingContext.setState((current) => {
      if (current.projectId !== context.projectId || current.datasetId !== context.datasetId) return current;
      return missingProject ? { projectId: null, datasetId: null } : { datasetId: null };
    });
  }, [canRepair, context.projectId, context.datasetId, missingProject, missingDataset, mismatchedDataset]);

  return {
    ...context,
    project,
    dataset,
    projects,
    datasets,
    projectLoading: projects.isPending || selectedProject.isFetching,
    datasetLoading: datasets.isPending || selectedDataset.isFetching,
  };
}
