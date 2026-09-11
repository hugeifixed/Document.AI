import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { list, tableParams } from "@/api/client";
import type { ExtractedField } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { FileNameLink } from "@/components/FileNameLink";
import { ConfidenceCue, Field, PageHeader, StatusChip, TableSearch } from "@/components/ui";
import { useDebouncedSearch, useTableState } from "@/hooks/useTableState";
import { useRunCollection } from "@/runs/lifecycle";
import { useWorkingContext } from "@/workspace/context";

export function Results() {
  const { projectId, datasetId } = useWorkingContext();
  const { state, update } = useTableState(["run", "review_status", "validation_status", "grounded", "name"]);
  const runs = useRunCollection({ purpose: "results", projectId, datasetId });
  const q = useQuery({ queryKey: ["fields", projectId, datasetId, state], queryFn: ({ signal }) => list<ExtractedField>("/fields/", { ...tableParams(state), ...(projectId ? { project: projectId } : {}), ...(datasetId ? { dataset: datasetId } : {}) }, { signal }) });
  const [search, setSearch] = useDebouncedSearch(state.q, (v) => update({ q: v }));
  const previousContext = useRef({ projectId, datasetId });
  useEffect(() => {
    const changed = previousContext.current.projectId !== projectId || previousContext.current.datasetId !== datasetId;
    previousContext.current = { projectId, datasetId };
    if (changed && state.filters.run) update({ filters: { run: "" } });
  }, [datasetId, projectId, state.filters.run, update]);
  return (
    <div>
      <PageHeader title="Extracted results">Extracted fields with raw and normalized values, scores, validation, and grounding.</PageHeader>
      <div className="mb-4 grid items-start gap-x-4 gap-y-3 sm:grid-cols-2 xl:grid-cols-5">
        <Field id="results-run" label="Run"><select id="results-run" className="select select-sm w-full border-(--border-interactive)" value={state.filters.run || ""} onChange={(e) => update({ filters: { run: e.target.value } })}><option value="">All runs</option>{runs.data?.results.map((r) => <option key={r.id} value={r.id}>{r.name || r.workflow_name} ({r.status})</option>)}</select></Field>
        <Field id="results-review" label="Review"><select id="results-review" className="select select-sm w-full border-(--border-interactive)" value={state.filters.review_status || ""} onChange={(e) => update({ filters: { review_status: e.target.value } })}><option value="">All</option>{["needs_review", "auto_accepted", "accepted", "corrected", "rejected", "absent"].map((s) => <option key={s}>{s}</option>)}</select></Field>
        <Field id="results-validation" label="Validation"><select id="results-validation" className="select select-sm w-full border-(--border-interactive)" value={state.filters.validation_status || ""} onChange={(e) => update({ filters: { validation_status: e.target.value } })}><option value="">All</option>{["passed", "failed", "warning", "not_run"].map((s) => <option key={s}>{s}</option>)}</select></Field>
        <Field id="results-grounded" label="Grounded"><select id="results-grounded" className="select select-sm w-full border-(--border-interactive)" value={state.filters.grounded || ""} onChange={(e) => update({ filters: { grounded: e.target.value } })}><option value="">All</option><option value="true">Yes</option><option value="false">No</option></select></Field>
        <TableSearch id="results-search" value={search} onChange={setSearch} placeholder="Field, value, or document" />
      </div>
      <DataTable<ExtractedField> caption="Extracted fields" data={q.data} isLoading={q.isLoading} isFetching={q.isFetching} error={q.error as Error} onRetry={() => q.refetch()} state={state} update={update} getRowId={(r) => r.id}
        columns={[{ id: "document__original_filename", header: "Document", enableSorting: false, accessorKey: "document_name", cell: (c) => <FileNameLink name={c.getValue<string>()} to={`/review/${c.row.original.document}?run=${c.row.original.run}`} /> },
                  { id: "name", header: "Field", accessorKey: "name" },
                  { id: "raw_value", header: "Value", enableSorting: false, accessorKey: "raw_value", cell: (c) => <span className="font-mono">{c.getValue<string | null>() ?? <em className="text-secondary">null</em>}</span> },
                  { id: "normalized_value", header: "Normalized", enableSorting: false, accessorKey: "normalized_value", cell: (c) => <span className="font-mono text-sm">{c.getValue<string | null>() ?? ""}</span> },
                  { id: "score", header: "Confidence", accessorKey: "score", cell: (c) => <ConfidenceCue score={c.getValue<number | null>()} status={c.row.original.review_status} label={c.row.original.name} /> },
                  { id: "validation_status", header: "Validation", accessorKey: "validation_status", cell: (c) => <span title={c.row.original.validation_messages.join("; ")}><StatusChip status={c.getValue<string>()} /></span> },
                  { id: "review_status", header: "Review", accessorKey: "review_status", cell: (c) => <StatusChip status={c.getValue<string>()} /> },
                  { id: "grounded", header: "Grounded", enableSorting: false, accessorKey: "grounded", cell: (c) => c.getValue<boolean>() ? `yes (${c.row.original.spans[0]?.mapping_method ?? ""})` : "no" }]} />
    </div>
  );
}
