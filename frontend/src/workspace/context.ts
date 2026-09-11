import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { get } from "@/api/client";
import type { Dataset, Project } from "@/api/types";

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

/** Resolves persisted identifiers and repairs selections removed by another user. */
export function useResolvedWorkingContext() {
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

  useEffect(() => {
    if (
      projects.isSuccess &&
      context.projectId &&
      !projects.data.results.some((project) => project.id === context.projectId)
    ) {
      context.clear();
    }
  }, [context, projects.data, projects.isSuccess]);

  useEffect(() => {
    if (
      datasets.isSuccess &&
      context.datasetId &&
      !datasets.data.results.some((dataset) => dataset.id === context.datasetId)
    ) {
      context.selectDataset(null);
    }
  }, [context, datasets.data, datasets.isSuccess]);

  const project = projects.data?.results.find((candidate) => candidate.id === context.projectId);
  const dataset = datasets.data?.results.find((candidate) => candidate.id === context.datasetId);

  return { ...context, project, dataset, projects, datasets };
}
