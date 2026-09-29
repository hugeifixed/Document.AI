export const playgroundKeys = {
  all: ["workflow-playground"] as const,
  sessions: (project: string) => [...playgroundKeys.all, "sessions", project] as const,
  session: (id: string) => [...playgroundKeys.all, "session", id] as const,
  documents: (dataset: string | null, search: string) => [...playgroundKeys.all, "documents", dataset, search] as const,
};
