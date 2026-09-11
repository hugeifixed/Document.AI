import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { RowSelectionState } from "@tanstack/react-table";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ApiError, list, post, tableParams } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { ExtractedField } from "@/api/types";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable } from "@/components/DataTable";
import { FileNameLink } from "@/components/FileNameLink";
import { ConfidenceCue, PageHeader, StatusChip, TableSearch } from "@/components/ui";
import { useDebouncedSearch, useTableState } from "@/hooks/useTableState";
import { usePrefs } from "@/store/prefs";

export function ReviewQueue() {
  const { user } = useSession();
  const canReview = !!user?.roles.includes("docai_reviewers");
  const qc = useQueryClient();
  const { projectId, datasetId } = usePrefs();
  const { state, update } = useTableState(["name"]);
  const [search, setSearch] = useDebouncedSearch(state.q, (value) => update({ q: value }));
  const q = useQuery({ queryKey: ["fields", "queue", projectId, datasetId, state], queryFn: ({ signal }) => list<ExtractedField>("/fields/", { ...tableParams(state), review_status: "needs_review", ...(projectId ? { project: projectId } : {}), ...(datasetId ? { dataset: datasetId } : {}) }, { signal }) });
  const [sel, setSel] = useState<RowSelectionState>({});
  const [confirm, setConfirm] = useState<"accept" | "reject" | null>(null);
  const selectionScope = `${projectId ?? ""}:${datasetId ?? ""}:${state.page}:${state.pageSize}:${state.sort ?? ""}:${state.desc ?? false}:${state.q ?? ""}:${JSON.stringify(state.filters)}`;
  useEffect(() => { setSel({}); setConfirm(null); }, [selectionScope]);
  const ids = (q.data?.results ?? []).map((field) => field.id).filter((id) => sel[id]);
  const bulk = useMutation({ mutationFn: ({ action, reason }: { action: "accept" | "reject"; reason: string }) => post<{ applied: string[]; skipped: unknown[] }>("/fields/bulk-review/", { field_ids: ids, action, confirm_count: ids.length, reason }),
    onSuccess: (r) => { toast.success(`${r.applied.length} field(s) updated`); setSel({}); setConfirm(null); qc.invalidateQueries({ queryKey: ["fields"] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); }, onError: (e: ApiError) => toast.error(`${e.message} (${e.code})`) });
  return (
    <div>
      <PageHeader title="Review queue" action={canReview && ids.length > 0 && <div className="flex gap-2"><button className="btn btn-sm btn-outline" disabled={bulk.isPending} onClick={() => setConfirm("accept")}>Accept {ids.length}</button><button className="btn btn-sm btn-outline btn-error" disabled={bulk.isPending} onClick={() => setConfirm("reject")}>Reject {ids.length}</button></div>}>
        Fields routed to a human: low score, missing grounding, validation failure, or disagreement. Open a document to review in context.
      </PageHeader>
      {!canReview && <output className="alert mb-6">This is a read-only view. Reviewing fields requires the reviewer role.</output>}
      <TableSearch id="review-queue-search" className="mb-4 max-w-sm" value={search} onChange={setSearch} placeholder="Document, field, or value" />
      <DataTable<ExtractedField> caption="Fields needing review" data={q.data} isLoading={q.isLoading} isFetching={q.isFetching} error={q.error as Error} onRetry={() => q.refetch()} state={state} update={update} getRowId={(r) => r.id}
        selection={canReview ? sel : undefined} onSelectionChange={canReview ? setSel : undefined} rowName={(r) => `${r.document_name} ${r.name}`} emptyText="The queue is empty."
        columns={[{ id: "document__original_filename", header: "Document", enableSorting: false, accessorKey: "document_name", cell: (c) => <FileNameLink name={c.getValue<string>()} to={`/review/${c.row.original.document}?run=${c.row.original.run}&field=${c.row.original.id}`} /> },
                  { id: "name", header: "Field", accessorKey: "name" }, { id: "raw_value", header: "Value", enableSorting: false, accessorKey: "raw_value", cell: (c) => <span className="font-mono">{c.getValue<string | null>() ?? <em>null</em>}</span> },
                  { id: "score", header: "Confidence", accessorKey: "score", cell: (c) => <ConfidenceCue score={c.getValue<number | null>()} label={c.row.original.name} /> },
                  { id: "validation_status", header: "Validation", accessorKey: "validation_status", cell: (c) => <><StatusChip status={c.getValue<string>()} />{c.row.original.validation_messages[0] && <span className="ml-2 text-caption">{c.row.original.validation_messages[0]}</span>}</> },
                  { id: "grounded", header: "Grounded", enableSorting: false, accessorKey: "grounded", cell: (c) => (c.getValue<boolean>() ? "yes" : "no") }]} />
      <ConfirmDialog pending={bulk.isPending} open={canReview && !!confirm} title={`${confirm === "accept" ? "Accept" : "Reject"} ${ids.length} field(s)`} confirmLabel={confirm === "accept" ? "Accept all" : "Reject all"} typed={String(ids.length)} destructive={confirm === "reject"} reasonLabel={confirm === "reject" ? "Reason" : "Review note (optional)"} reasonRequired={confirm === "reject"} reasonHelp="This note is recorded with each selected field." onClose={() => setConfirm(null)} onConfirm={(reason) => { if (confirm) bulk.mutate({ action: confirm, reason }); }}
        summary={<p>This applies to {ids.length} selected field(s). Original predictions are preserved; each action is recorded with your name. Type the count to confirm.</p>} />
    </div>
  );
}
