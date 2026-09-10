import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "light" | "dark" | "system";
interface Prefs {
  theme: Theme; setTheme: (t: Theme) => void;
  pageSize: number; setPageSize: (n: number) => void;
  projectId: string | null; datasetId: string | null; setContext: (p: string | null, d: string | null) => void;
}
export const usePrefs = create<Prefs>()(persist((set) => ({
  theme: "system", setTheme: (theme) => set({ theme }),
  pageSize: 25, setPageSize: (pageSize) => set({ pageSize }),
  projectId: null, datasetId: null, setContext: (projectId, datasetId) => set({ projectId, datasetId }),
}), { name: "docai-prefs" }));

export function applyTheme(t: Theme) {
  const el = document.documentElement;
  if (t === "system") el.removeAttribute("data-theme"); else el.setAttribute("data-theme", `extract-${t}`);
}
