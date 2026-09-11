import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { list, tableParams } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { Document, Label } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { Card, EmptyState, PageHeader, StatusChip, TableSearch } from "@/components/ui";
import { useDebouncedSearch, useTableState } from "@/hooks/useTableState";
import { usePrefs } from "@/store/prefs";

export function Labeling() {
  const { user } = useSession();
  const canReview = !!user?.roles.includes("docai_reviewers");
  const datasetId = usePrefs((s) => s.datasetId);
  const { state, update } = useTableState([]);
  const [search, setSearch] = useDebouncedSearch(state.q, (value) => update({ q: value }));
  const docs = useQuery({ queryKey: ["documents", "label", datasetId, state], enabled: !!datasetId, queryFn: () => list<Document>("/documents/", { ...tableParams(state), dataset: datasetId, status__in: "validated,processed" }) });
  const labels = useQuery({ queryKey: ["labels", datasetId], enabled: !!datasetId, queryFn: () => list<Label>("/labels/", { page_size: 200, document__dataset: datasetId, status: "final" }) });
  if (!canReview) return <div><PageHeader title="Ground truth" /><EmptyState text="Creating ground truth requires the reviewer role." action={<Link to="/results" className="btn btn-outline btn-sm">View extracted results</Link>} /></div>;
  if (!datasetId) return <div><PageHeader title="Ground truth" /><EmptyState text="Select a dataset in the sidebar to label its documents." /></div>;
  const counts = new Map<string, number>(); labels.data?.results.forEach((l) => counts.set(l.document, (counts.get(l.document) ?? 0) + 1));
  return (
    <div>
      <PageHeader title="Ground truth">Create verified labels by selecting text in each document. Every label retains its source location and mapping quality.</PageHeader>
      <Card className="mb-6"><p className="text-sm">Labels in this dataset: <strong className="tabular-nums">{labels.data?.count ?? "…"}</strong> final. Image-only pages use word-box selection; spreadsheets use cell ranges.</p></Card>
      <TableSearch id="ground-truth-documents-search" className="mb-4 max-w-sm" value={search} onChange={setSearch} placeholder="File name or document text" />
      <DataTable<Document> caption="Documents to label" data={docs.data} isLoading={docs.isLoading} error={docs.error as Error} onRetry={() => docs.refetch()} state={state} update={update} getRowId={(r) => r.id}
        columns={[{ id: "original_filename", header: "File", accessorKey: "original_filename", cell: (c) => <Link className="link link-primary" to={`/labeling/${c.row.original.id}`}>{c.getValue<string>()}</Link> },
                  { id: "file_format", header: "Format", accessorKey: "file_format" }, { id: "page_count", meta: { numeric: true }, header: "Units", enableSorting: false, accessorFn: (r) => r.sheet_count || r.page_count },
                  { id: "labels", meta: { numeric: true }, header: "Labels", enableSorting: false, accessorFn: (r) => counts.get(r.id) ?? 0, cell: (c) => <span className="tabular-nums">{c.getValue<number>()}</span> },
                  { id: "status", header: "Status", accessorKey: "status", cell: (c) => <StatusChip status={c.getValue<string>()} /> }]} />
    </div>
  );
}
