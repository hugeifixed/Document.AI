import { useQuery } from "@tanstack/react-query";
import { get, list, tableParams } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { ExtractedField, Run } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { FileNameLink } from "@/components/FileNameLink";
import { JourneyCue } from "@/components/JourneyCue";
import { ConfidenceCue, Field, PageHeader, StatusChip, TableSearch } from "@/components/ui";
import { useDebouncedSearch, useTableState } from "@/hooks/useTableState";
import { nextResultsAction } from "@/journey/guidance";
import { useRunCollection } from "@/runs/lifecycle";
import { useWorkingContext } from "@/workspace/context";
import { fieldDisplayName, fieldDisplayValue } from "@/fieldPresentation";

export function Results() {
  const { user } = useSession();
  const { projectId, datasetId } = useWorkingContext();
  const { state, update } = useTableState(["run", "review_status", "validation_status", "grounded", "name"]);
  const runs = useRunCollection({ purpose: "results", projectId, datasetId });
  const q = useQuery({
    queryKey: ["fields", projectId, datasetId, state],
    queryFn: ({ signal }) =>
      list<ExtractedField>(
        "/fields/",
        {
          ...tableParams(state),
          ...(projectId ? { project: projectId } : {}),
          ...(datasetId ? { dataset: datasetId } : {}),
        },
        { signal },
      ),
  });
  const [search, setSearch] = useDebouncedSearch(state.q, (v) => update({ q: v }));
  const selectedRunId = state.filters.run;
  const selectedRun = useQuery({
    queryKey: ["run", selectedRunId],
    enabled: !!selectedRunId,
    queryFn: ({ signal }) => get<Run>(`/runs/${selectedRunId}/`, undefined, { signal }),
  });
  const nextAction = selectedRun.data ? nextResultsAction(selectedRun.data, user?.roles ?? []) : null;
  return (
    <div>
      <PageHeader title="Extracted results">
        Extracted fields with raw and normalized values, scores, validation, and grounding.
      </PageHeader>
      {nextAction && <JourneyCue action={nextAction} className="mb-6" />}
      <div className="mb-4 grid items-start gap-x-4 gap-y-3 sm:grid-cols-2 xl:grid-cols-5">
        <Field id="results-run" label="Run">
          <select
            id="results-run"
            className="select select-sm w-full border-(--border-interactive)"
            value={state.filters.run || ""}
            onChange={(e) => update({ filters: { run: e.target.value } })}
          >
            <option value="">All runs</option>
            {runs.data?.results.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name || r.workflow_name} ({r.status})
              </option>
            ))}
          </select>
        </Field>
        <Field id="results-review" label="Review">
          <select
            id="results-review"
            className="select select-sm w-full border-(--border-interactive)"
            value={state.filters.review_status || ""}
            onChange={(e) => update({ filters: { review_status: e.target.value } })}
          >
            <option value="">All</option>
            {["needs_review", "auto_accepted", "accepted", "corrected", "rejected", "absent"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </Field>
        <Field id="results-validation" label="Validation">
          <select
            id="results-validation"
            className="select select-sm w-full border-(--border-interactive)"
            value={state.filters.validation_status || ""}
            onChange={(e) => update({ filters: { validation_status: e.target.value } })}
          >
            <option value="">All</option>
            {["passed", "failed", "warning", "not_run"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </Field>
        <Field id="results-grounded" label="Grounded">
          <select
            id="results-grounded"
            className="select select-sm w-full border-(--border-interactive)"
            value={state.filters.grounded || ""}
            onChange={(e) => update({ filters: { grounded: e.target.value } })}
          >
            <option value="">All</option>
            <option value="true">Yes</option>
            <option value="false">No</option>
          </select>
        </Field>
        <TableSearch id="results-search" value={search} onChange={setSearch} placeholder="Field, value, or document" />
      </div>
      <DataTable<ExtractedField>
        caption="Extracted fields"
        data={q.data}
        isLoading={q.isLoading}
        isFetching={q.isFetching}
        error={q.error as Error}
        onRetry={() => q.refetch()}
        state={state}
        update={update}
        getRowId={(r) => r.id}
        columns={[
          {
            id: "document__original_filename",
            header: "Document",
            enableSorting: false,
            accessorKey: "document_name",
            cell: (c) => (
              <FileNameLink
                name={c.getValue<string>()}
                to={`/documents/${c.row.original.document}?run=${c.row.original.run}&from=results`}
              />
            ),
          },
          { id: "name", header: "Field", accessorKey: "name", cell: (c) => fieldDisplayName(c.row.original.name) },
          {
            id: "raw_value",
            header: "Value",
            enableSorting: false,
            accessorKey: "raw_value",
            cell: (c) => (
              <span className="font-mono">
                {fieldDisplayValue(c.row.original, c.getValue<string | null>()) ?? (
                  <em className="text-secondary">null</em>
                )}
              </span>
            ),
          },
          {
            id: "normalized_value",
            header: "Normalized",
            enableSorting: false,
            accessorKey: "normalized_value",
            cell: (c) => (
              <span className="font-mono text-sm">
                {fieldDisplayValue(c.row.original, c.getValue<string | null>()) ?? ""}
              </span>
            ),
          },
          {
            id: "score",
            header: "Model confidence",
            accessorKey: "score",
            cell: (c) => (
              <ConfidenceCue
                score={c.getValue<number | null>()}
                status={c.row.original.review_status}
                label={fieldDisplayName(c.row.original.name)}
              />
            ),
          },
          {
            id: "validation_status",
            header: "Validation",
            accessorKey: "validation_status",
            cell: (c) => (
              <span title={c.row.original.validation_messages.join("; ")}>
                <StatusChip status={c.getValue<string>()} />
              </span>
            ),
          },
          {
            id: "review_status",
            header: "Review",
            accessorKey: "review_status",
            cell: (c) => <StatusChip status={c.getValue<string>()} />,
          },
          {
            id: "grounded",
            header: "Grounded",
            enableSorting: false,
            accessorKey: "grounded",
            cell: (c) =>
              c.getValue<boolean>()
                ? `yes (${c.row.original.spans[0]?.mapping_method === "selection_mark" ? "checkbox location" : (c.row.original.spans[0]?.mapping_method ?? "")})`
                : "no",
          },
        ]}
        emptyText={
          selectedRunId
            ? "This run did not produce extracted fields that match the current filters."
            : "No extracted results are available in the selected context. Start or open a completed run first."
        }
      />
    </div>
  );
}
