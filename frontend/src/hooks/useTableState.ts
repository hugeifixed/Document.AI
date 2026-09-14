/** URL-synchronized table state (page, page_size, sort, q, filters) — refresh, deep links and back/forward all preserve the view. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { usePrefs } from "@/store/prefs";

export interface TableState {
  page: number;
  pageSize: number;
  sort?: string;
  desc?: boolean;
  q?: string;
  filters: Record<string, string>;
}

export function useTableState(filterKeys: string[] = [], defaults?: { pageSize?: number; sort?: string }) {
  const [sp, setSp] = useSearchParams();
  const defaultSize = usePrefs((s) => s.pageSize);
  const filterKeySignature = filterKeys.join("\u0000");
  const stableFilterKeys = useMemo(
    () => (filterKeySignature ? filterKeySignature.split("\u0000") : []),
    [filterKeySignature],
  );
  const state: TableState = useMemo(() => {
    const f: Record<string, string> = {};
    for (const k of stableFilterKeys) {
      const v = sp.get(k);
      if (v) f[k] = v;
    }
    const sort = sp.get("sort") || defaults?.sort;
    return {
      page: Number(sp.get("page") || 1),
      pageSize: Number(sp.get("page_size") || defaults?.pageSize || defaultSize),
      sort: sort?.replace(/^-/, ""),
      desc: sort?.startsWith("-"),
      q: sp.get("q") || undefined,
      filters: f,
    };
  }, [sp, defaultSize, stableFilterKeys, defaults?.pageSize, defaults?.sort]);
  const update = useCallback(
    (patch: Partial<TableState>) => {
      const next = new URLSearchParams(sp);
      const merged = { ...state, ...patch, filters: { ...state.filters, ...(patch.filters || {}) } };
      next.set("page", String(patch.page ?? (patch.q !== undefined || patch.filters ? 1 : merged.page)));
      next.set("page_size", String(merged.pageSize));
      if (merged.sort) next.set("sort", (merged.desc ? "-" : "") + merged.sort);
      else next.delete("sort");
      if (merged.q) next.set("q", merged.q);
      else next.delete("q");
      for (const k of stableFilterKeys) {
        const v = merged.filters[k];
        if (v) next.set(k, v);
        else next.delete(k);
      }
      setSp(next, { replace: true });
    },
    [sp, setSp, state, stableFilterKeys],
  );
  return { state, update };
}

/** Debounced search input bound to table state (250-400ms per DESIGN.md §10.4). */
export function useDebouncedSearch(initial: string | undefined, onChange: (q: string) => void, delay = 300) {
  const [value, setValue] = useState(initial || "");
  const t = useRef<number>(undefined);
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);
  useEffect(() => {
    window.clearTimeout(t.current);
    setValue(initial || "");
  }, [initial]);
  useEffect(() => () => window.clearTimeout(t.current), []);
  const set = useCallback(
    (v: string) => {
      setValue(v);
      window.clearTimeout(t.current);
      t.current = window.setTimeout(() => onChangeRef.current(v), delay);
    },
    [delay],
  );
  return [value, set] as const;
}
