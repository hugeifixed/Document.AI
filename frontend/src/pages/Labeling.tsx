import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { usePageTitleState } from "@/common/hooks/use-page-title-state";
import { list, tableParams } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { Document, Label } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { FileNameLink } from "@/components/FileNameLink";
import { Card, EmptyState, PageHeader, StatusChip, TableSearch } from "@/components/ui";
import { useDebouncedSearch, useTableState } from "@/hooks/useTableState";
import { useRunCollection } from "@/runs/lifecycle";
import { useWorkingContext } from "@/workspace/context";

export function Labeling() {
  const { user } = useSession();
  const canReview = !!user?.roles.includes("docai_reviewers");
  usePageTitleState(!canReview ? "Access Denied" : undefined);
  const { projectId, datasetId } = useWorkingContext();
  const { state, update } = useTableState([]);
  const [search, setSearch] = useDebouncedSearch(state.q, (value) => update({ q: value }));
  const docs = useQuery({
    queryKey: ["documents", "label", datasetId, state],
    enabled: !!datasetId,
    queryFn: ({ signal }) =>
      list<Document>(
        "/documents/",
        { ...tableParams(state), dataset: datasetId, status__in: "validated,processed" },
        { signal },
      ),
  });
  const labels = useQuery({
    queryKey: ["labels", datasetId],
    enabled: !!datasetId,
    queryFn: ({ signal }) =>
      list<Label>("/labels/", { page_size: 200, document__dataset: datasetId, status: "final" }, { signal }),
  });
  const completedRuns = useRunCollection({ purpose: "evaluation", projectId, datasetId });
  if (!canReview)
    return (
      <div>
        <PageHeader title="Ground truth" />
        <EmptyState
          text="Creating ground truth requires the reviewer role."
          action={
            <Link to="/results" className="btn btn-outline btn-sm">
              View extracted results
            </Link>
          }
        />
      </div>
    );
  if (!datasetId)
    return (
      <div>
        <PageHeader title="Ground truth" />
        <EmptyState text="Select a dataset in the sidebar to label its documents." />
      </div>
    );
  const counts = new Map<string, number>();
  labels.data?.results.forEach((l) => counts.set(l.document, (counts.get(l.document) ?? 0) + 1));
  return (
    <div>
      <PageHeader title="Ground truth">
        Create verified labels by selecting text in each document. Every label retains its source location and mapping
        quality.
      </PageHeader>
      <Card className="mb-6">
        <p className="text-sm">
          Labels in this dataset: <strong className="tabular-nums">{labels.data?.count ?? "…"}</strong> final.
          Image-only pages use word-box selection; spreadsheets use cell ranges.
        </p>
        {!!labels.data?.count && completedRuns.data?.results[0] && (
          <Link
            className="link link-primary mt-2 inline-block text-sm font-medium"
            to={`/evaluation?run=${completedRuns.data.results[0].id}`}
          >
            Evaluate current labels
          </Link>
        )}
      </Card>
      <TableSearch
        id="ground-truth-documents-search"
        className="mb-4 max-w-sm"
        value={search}
        onChange={setSearch}
        placeholder="File name or document text"
      />
      <DataTable<Document>
        caption="Documents to label"
        data={docs.data}
        isLoading={docs.isLoading}
        error={docs.error as Error}
        onRetry={() => docs.refetch()}
        state={state}
        update={update}
        getRowId={(r) => r.id}
        emptyText="No validated documents are available for labeling in this dataset. Upload and validate documents first."
        columns={[
          {
            id: "original_filename",
            header: "File",
            accessorKey: "original_filename",
            cell: (c) => <FileNameLink name={c.getValue<string>()} to={`/labeling/${c.row.original.id}`} />,
          },
          { id: "file_format", header: "Format", accessorKey: "file_format" },
          {
            id: "page_count",
            meta: { numeric: true },
            header: "Units",
            enableSorting: false,
            accessorFn: (r) => r.sheet_count || r.page_count,
          },
          {
            id: "labels",
            meta: { numeric: true },
            header: "Labels",
            enableSorting: false,
            accessorFn: (r) => counts.get(r.id) ?? 0,
            cell: (c) => <span className="tabular-nums">{c.getValue<number>()}</span>,
          },
          {
            id: "labeling_status",
            header: "Labeling",
            enableSorting: false,
            accessorFn: (r) => counts.get(r.id) ?? 0,
            cell: (c) => <StatusChip status={c.getValue<number>() > 0 ? "in_progress" : "not_started"} />,
          },
          {
            id: "status",
            header: "Status",
            accessorKey: "status",
            cell: (c) => <StatusChip status={c.getValue<string>()} />,
          },
        ]}
      />
    </div>
  );
}
