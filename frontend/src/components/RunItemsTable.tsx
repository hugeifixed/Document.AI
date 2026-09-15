import { Field } from "@/common/components/ui/field/field";
import { useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import type { LLMUsageSummary, Page, RunItem } from "@/common/types/api";
import { DataTable } from "@/components/DataTable";
import { FileNameLink } from "@/components/FileNameLink";
import { ITEM_FILTERS } from "@/components/RunProgress";
import { ScanEnhancementSummary } from "@/components/ScanEnhancementSummary";
import { StatusChip, TableSearch } from "@/components/ui";

import { type TableState, useDebouncedSearch } from "@/hooks/useTableState";

type ItemRow = RunItem & { total_tokens: number | null };

export function RunItemsTable({
  runId,
  data,
  loading,
  fetching,
  error,
  onRetry,
  state,
  update,
  selectedFilter,
  onFilter,
  canOperate,
  usage,
}: {
  runId: string;
  data: Page<RunItem> | undefined;
  loading: boolean;
  fetching: boolean;
  error: Error | null;
  onRetry: () => void;
  state: TableState;
  update: (patch: Partial<TableState>) => void;
  selectedFilter: string;
  onFilter: (status: string) => void;
  canOperate: boolean;
  usage: LLMUsageSummary | undefined;
}) {
  const [search, setSearch] = useDebouncedSearch(state.q, (q) => update({ q }));
  const usageByItem = new Map((usage?.by_item ?? []).map((item) => [item.run_item, item]));
  const columns = useMemo<ColumnDef<ItemRow, unknown>[]>(
    () => [
      {
        id: "document_name",
        header: "Document",
        accessorKey: "document_name",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex min-h-6 max-w-64 items-center [&_a]:max-w-full">
            <FileNameLink
              name={row.original.document_name}
              to={`/documents/${row.original.document}?run=${row.original.run}&from=run`}
            />
          </div>
        ),
      },
      {
        id: "status",
        header: "Status",
        accessorKey: "status",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="flex min-h-6 items-center">
              <StatusChip status={row.original.status} />
            </div>
            <ScanEnhancementSummary item={row.original} />
          </>
        ),
      },
      {
        id: "attempts",
        header: "Attempts",
        accessorKey: "attempts",
        enableSorting: false,
        meta: { numeric: true },
        cell: ({ row }) => (
          <div className="flex min-h-6 items-center justify-end">{row.original.attempts.toLocaleString()}</div>
        ),
      },
      {
        id: "duration_ms",
        header: "Duration",
        accessorKey: "duration_ms",
        enableSorting: false,
        meta: { numeric: true },
        cell: ({ row }) => (
          <div className="flex min-h-6 items-center justify-end whitespace-nowrap">
            {row.original.duration_ms != null ? `${row.original.duration_ms.toLocaleString()} ms` : "—"}
          </div>
        ),
      },
      ...(canOperate
        ? [
            {
              id: "tokens",
              header: "LLM tokens",
              enableSorting: false,
              meta: { numeric: true },
              cell: ({ row }: { row: { original: ItemRow } }) => (
                <div className="flex min-h-6 items-center justify-end">
                  {row.original.total_tokens?.toLocaleString() ?? "—"}
                </div>
              ),
            },
          ]
        : []),
      {
        id: "error",
        header: "Error",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.error_code && (
            <div className="grid min-w-48 max-w-72 justify-items-start gap-2 whitespace-normal text-sm [overflow-wrap:anywhere]">
              <p className="flex min-h-6 items-center font-mono text-caption">{row.original.error_code}</p>
              <p className="text-secondary">{row.original.error_message}</p>
              {row.original.retryable && <span className="badge badge-ghost badge-sm">Retry available</span>}
            </div>
          ),
      },
    ],
    [canOperate],
  );
  const rows = data
    ? {
        ...data,
        results: data.results.map((item) => ({
          ...item,
          run: runId,
          total_tokens: usageByItem.get(item.id)?.total_tokens ?? null,
        })),
      }
    : undefined;
  return (
    <section
      id="run-items"
      tabIndex={-1}
      className="mb-6 min-w-0 scroll-mt-24 rounded-box [&_td]:align-top [&_th]:align-top"
      aria-labelledby="run-items-title"
    >
      <h2 id="run-items-title" className="mb-4">
        Items ({data?.count.toLocaleString() ?? "…"})
      </h2>
      <div className="mb-4 grid items-end gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(12rem,auto)]">
        <TableSearch
          id="run-items-search"
          value={search}
          onChange={setSearch}
          placeholder="Search documents"
          className="[&_input]:h-11 sm:[&_input]:h-10"
        />
        <Field id="run-items-status" label="Document status">
          <select
            id="run-items-status"
            className="select h-11 w-full border-(--border-interactive) sm:h-10"
            value={selectedFilter}
            onChange={(event) => onFilter(event.target.value)}
          >
            {ITEM_FILTERS.map((filter) => (
              <option key={filter.value} value={filter.value}>
                {filter.label}
              </option>
            ))}
            <option value="running,queued">Active</option>
          </select>
        </Field>
      </div>
      <DataTable<ItemRow>
        caption="Run items"
        data={rows}
        isLoading={loading}
        isFetching={fetching}
        error={error}
        onRetry={onRetry}
        state={state}
        update={update}
        getRowId={(item) => item.id}
        emptyText="No documents match these filters."
        columns={columns}
      />
    </section>
  );
}
