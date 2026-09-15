/** TanStack Table as a headless controller over server-paginated API data (§10.4).
 *  Semantic HTML, real <button>s in headers with aria-sort, row selection with
 *  accessible checkbox names, sticky opaque header, explicit loading/empty/error. */
import { ChevronDownIcon, ChevronUpDownIcon, ChevronUpIcon } from "@heroicons/react/20/solid";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  type RowData,
  type RowSelectionState,
  useReactTable,
} from "@tanstack/react-table";
import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { announce } from "@/a11y/announce";
import type { Page } from "@/common/types/api";
import type { TableState } from "@/hooks/useTableState";
import { ErrorNotice } from "./ErrorNotice";

import { ScrollRegion } from "@/common/components/ui/scroll-region/scroll-region";
import { Skeleton } from "@/common/components/ui/skeleton/skeleton";


declare module "@tanstack/react-table" {
  // Column metadata keeps numeric presentation explicit, including empty datasets.
  interface ColumnMeta<TData extends RowData, TValue> {
    numeric?: boolean;
  }
}

interface Props<T> {
  columns: ColumnDef<T, unknown>[];
  data?: Page<T>;
  state: TableState;
  update: (p: Partial<TableState>) => void;
  isLoading: boolean;
  isFetching?: boolean;
  error?: Error | null;
  caption: string;
  rowName?: (r: T) => string;
  getRowId: (r: T) => string;
  selection?: RowSelectionState;
  onSelectionChange?: (s: RowSelectionState) => void;
  onRowOpen?: (r: T) => void;
  emptyText?: ReactNode;
  onRetry?: () => void;
}

export function DataTable<T>({
  columns,
  data,
  state,
  update,
  isLoading,
  isFetching,
  error,
  caption,
  rowName,
  getRowId,
  selection,
  onSelectionChange,
  onRowOpen,
  emptyText = "Nothing here yet.",
  onRetry,
}: Props<T>) {
  const table = useReactTable({
    data: data?.results ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
    getRowId,
    enableRowSelection: !!onSelectionChange,
    state: { rowSelection: selection ?? {} },
    onRowSelectionChange: (u) => onSelectionChange?.(typeof u === "function" ? u(selection ?? {}) : u),
    pageCount: data?.total_pages ?? -1,
  });
  const lastAnnouncement = useRef<string>(undefined);
  const resultCount = data?.count;
  const resultPage = data?.page;
  const resultPages = data?.total_pages;
  useEffect(() => {
    const message = isLoading
      ? `Loading ${caption.toLowerCase()}…`
      : resultCount !== undefined && resultPage !== undefined && resultPages !== undefined
        ? `${resultCount} results, page ${resultPage} of ${Math.max(resultPages, 1)}`
        : undefined;
    if (message && message !== lastAnnouncement.current) announce(message);
    lastAnnouncement.current = message;
  }, [caption, isLoading, resultCount, resultPage, resultPages]);
  const columnCount = columns.length + (onSelectionChange ? 1 : 0);
  const sortBy = (id: string) => {
    const desc = state.sort === id ? !state.desc : false;
    update({ sort: id, desc, page: 1 });
    announce(`Sorted by ${id} ${desc ? "descending" : "ascending"}`);
  };
  return (
    <div className="elevation-raised min-w-0 rounded-box border border-base-300 bg-base-100">
      <ScrollRegion label={caption} className="rounded-t-box">
        <table className="table" aria-busy={isFetching || isLoading}>
          <caption className="sr-only">{caption}</caption>
          <thead className="sticky top-0 z-10 bg-base-100">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {onSelectionChange && (
                  <th scope="col" className="w-10">
                    <input
                      type="checkbox"
                      className="checkbox checkbox-sm"
                      aria-label="Select all rows on this page"
                      checked={table.getIsAllPageRowsSelected()}
                      onChange={table.getToggleAllPageRowsSelectedHandler()}
                    />
                  </th>
                )}
                {hg.headers.map((h) => {
                  const canSort = h.column.getCanSort() && h.column.columnDef.enableSorting !== false;
                  const active = state.sort === h.column.id;
                  return (
                    <th
                      key={h.id}
                      scope="col"
                      className={h.column.columnDef.meta?.numeric ? "text-end" : undefined}
                      aria-sort={active ? (state.desc ? "descending" : "ascending") : "none"}
                    >
                      {canSort ? (
                        <button
                          type="button"
                          className="inline-flex min-h-6 items-center gap-1 text-inherit font-medium hover:text-base-content"
                          onClick={() => sortBy(h.column.id)}
                        >
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {active ? (
                            state.desc ? (
                              <ChevronDownIcon className="size-4" aria-hidden />
                            ) : (
                              <ChevronUpIcon className="size-4" aria-hidden />
                            )
                          ) : (
                            <ChevronUpDownIcon className="size-4 opacity-70" aria-hidden />
                          )}
                        </button>
                      ) : (
                        flexRender(h.column.columnDef.header, h.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {isLoading &&
              Array.from({ length: 5 }, (_, row) => (
                <tr key={row} aria-hidden="true" className="h-11">
                  {Array.from({ length: columnCount }, (_, column) => (
                    <td key={column}>
                      <Skeleton className={`${column === 0 ? "w-24" : "w-16"} h-4 max-w-full`} />
                    </td>
                  ))}
                </tr>
              ))}
            {error && !isLoading && (
              <tr>
                <td colSpan={columnCount} className="p-6">
                  <ErrorNotice message={error.message} onRetry={onRetry} />
                </td>
              </tr>
            )}
            {!isLoading && !error && data && data.results.length === 0 && (
              <tr>
                <td colSpan={columnCount} className="p-8 text-center text-secondary">
                  {emptyText}
                </td>
              </tr>
            )}
            {!isLoading &&
              table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className={`h-12 ${row.getIsSelected() ? "bg-(--color-blue-soft)" : "hover:bg-base-200"}`}
                >
                  {onSelectionChange && (
                    <td>
                      <input
                        type="checkbox"
                        className="checkbox checkbox-sm"
                        aria-label={`Select ${rowName ? rowName(row.original) : row.id}`}
                        checked={row.getIsSelected()}
                        onChange={row.getToggleSelectedHandler()}
                      />
                    </td>
                  )}
                  {row.getVisibleCells().map((cell, i) => {
                    const content =
                      i === 0 && onRowOpen ? (
                        <button
                          type="button"
                          className="link link-primary text-left"
                          onClick={() => onRowOpen(row.original)}
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </button>
                      ) : (
                        flexRender(cell.column.columnDef.cell, cell.getContext())
                      );
                    const className = cell.column.columnDef.meta?.numeric
                      ? "whitespace-nowrap text-end lining-nums tabular-nums"
                      : i === 0
                        ? "whitespace-nowrap font-normal"
                        : undefined;
                    return i === 0 ? (
                      <th key={cell.id} scope="row" className={className}>
                        {content}
                      </th>
                    ) : (
                      <td key={cell.id} className={className}>
                        {content}
                      </td>
                    );
                  })}
                </tr>
              ))}
          </tbody>
        </table>
      </ScrollRegion>
      <nav
        className="flex flex-wrap items-center justify-between gap-3 border-t border-base-300 px-4 py-3 text-sm"
        aria-label="Pagination"
      >
        <span className="tabular-nums text-secondary">
          {isLoading ? "Loading results…" : data ? `${data.count} results` : ""}
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2">
            Rows
            <select
              className="select select-sm w-auto border-(--border-interactive)"
              value={state.pageSize}
              onChange={(e) => update({ pageSize: Number(e.target.value), page: 1 })}
            >
              {[10, 25, 50, 100].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn btn-sm btn-outline"
            disabled={state.page <= 1}
            onClick={() => update({ page: state.page - 1 })}
          >
            Previous
          </button>
          <span className="whitespace-nowrap tabular-nums">
            Page {data?.page ?? state.page} of {Math.max(data?.total_pages ?? 1, 1)}
          </span>
          <button
            type="button"
            className="btn btn-sm btn-outline"
            disabled={!data || state.page >= data.total_pages}
            onClick={() => update({ page: state.page + 1 })}
          >
            Next
          </button>
        </div>
      </nav>
    </div>
  );
}
