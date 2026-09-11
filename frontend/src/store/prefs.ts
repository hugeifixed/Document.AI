import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "light" | "dark" | "system";
interface Prefs {
  theme: Theme; setTheme: (t: Theme) => void;
  pageSize: number; setPageSize: (n: number) => void;
  sidebarHidden: boolean; setSidebarHidden: (hidden: boolean) => void;
}
export const usePrefs = create<Prefs>()(persist((set) => ({
  theme: "system", setTheme: (theme) => set({ theme }),
  pageSize: 25, setPageSize: (pageSize) => set({ pageSize }),
  sidebarHidden: false, setSidebarHidden: (sidebarHidden) => set({ sidebarHidden }),
}), {
  name: "docai-prefs",
  partialize: ({ theme, pageSize, sidebarHidden }) => ({ theme, pageSize, sidebarHidden }),
}));

export function applyTheme(t: Theme) {
  const el = document.documentElement;
  if (t === "system") el.removeAttribute("data-theme"); else el.setAttribute("data-theme", `extract-${t}`);
}
