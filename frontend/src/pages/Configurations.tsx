import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, get, list, post, tableParams } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { Workflow } from "@/api/types";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable } from "@/components/DataTable";
import { JourneyCue } from "@/components/JourneyCue";
import { fmtDate, PageHeader, ScrollRegion, StatusChip, TableSearch } from "@/components/ui";
import { useDebouncedSearch, useTableState } from "@/hooks/useTableState";
import { useWorkingContext } from "@/workspace/context";

export function Configurations() {
  const { user } = useSession();
  const canOperate = !!user?.roles.includes("docai_operators");
  const canApprove = !!user?.roles.includes("docai_approvers");
  const { projectId, datasetId } = useWorkingContext();
  const [searchParams] = useSearchParams();
  const createdWorkflowId = searchParams.get("created");
  const qc = useQueryClient();
  const { state, update } = useTableState(["status", "workflow_type"]);
  const [search, setSearch] = useDebouncedSearch(state.q, (value) => update({ q: value }));
  const q = useQuery({
    queryKey: ["workflows", projectId, state],
    queryFn: ({ signal }) =>
      list<Workflow>(
        "/workflows/",
        { ...tableParams(state), ...(projectId ? { project: projectId } : {}) },
        { signal },
      ),
  });
  const createdWorkflowQuery = useQuery({
    queryKey: ["workflow", createdWorkflowId],
    enabled: !!createdWorkflowId,
    queryFn: ({ signal }) => get<Workflow>(`/workflows/${createdWorkflowId}/`, undefined, { signal }),
  });
  const [confirmation, setConfirmation] = useState<{ workflow: Workflow; action: "approve" | "retire" } | null>(null);
  const [view, setView] = useState<Workflow | null>(null);
  const [recentlyApproved, setRecentlyApproved] = useState<Workflow | null>(null);
  useEffect(() => setRecentlyApproved(null), [projectId, datasetId]);
  const detail = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = detail.current;
    if (!dialog) return;
    if (view && !dialog.open) dialog.showModal();
    if (!view && dialog.open) dialog.close();
  }, [view]);
  const act = useMutation({
    mutationFn: ({ id, action, reason }: { id: string; action: "approve" | "retire"; reason: string }) =>
      post<Workflow>(`/workflows/${id}/${action}/`, { reason }),
    onSuccess: (workflow, v) => {
      toast.success(`Workflow version ${v.action}d`);
      if (v.action === "approve") setRecentlyApproved(workflow);
      qc.invalidateQueries({ queryKey: ["workflows"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setConfirmation(null);
    },
    onError: (e: ApiError) => toast.error(`${e.message} (${e.code})`),
  });
  const columns: ColumnDef<Workflow, unknown>[] = [
    { id: "name", header: "Name", accessorKey: "name" },
    {
      id: "version",
      meta: { numeric: true },
      header: "Version",
      accessorKey: "version",
      cell: (c) => <span className="tabular-nums">v{c.getValue<number>()}</span>,
    },
    {
      id: "workflow_type",
      header: "Type",
      accessorKey: "workflow_type",
      cell: (c) => <span className="font-mono text-caption">{c.getValue<string>()}</span>,
    },
    {
      id: "status",
      header: "Status",
      accessorKey: "status",
      cell: (c) => <StatusChip status={c.getValue<string>()} />,
    },
    {
      id: "content_hash",
      header: "Hash",
      accessorKey: "content_hash",
      enableSorting: false,
      cell: (c) => (
        <span className="font-mono text-caption" title={c.getValue<string>()}>
          {c.getValue<string>().slice(7, 19)}
        </span>
      ),
    },
    { id: "created", header: "Created", accessorKey: "created", cell: (c) => fmtDate(c.getValue<string>()) },
  ];
  if (canApprove)
    columns.push({
      id: "actions",
      header: "Actions",
      enableSorting: false,
      cell: (c) => (
        <div className="flex gap-1">
          {c.row.original.status === "draft" && (
            <button
              type="button"
              className="btn btn-xs btn-outline"
              disabled={act.isPending}
              onClick={() => setConfirmation({ workflow: c.row.original, action: "approve" })}
            >
              Approve
            </button>
          )}
          {c.row.original.status !== "retired" && (
            <button
              type="button"
              className="btn btn-xs btn-ghost"
              disabled={act.isPending}
              onClick={() => setConfirmation({ workflow: c.row.original, action: "retire" })}
            >
              Retire
            </button>
          )}
        </div>
      ),
    });
  const createdWorkflow =
    createdWorkflowQuery.data ?? q.data?.results.find((workflow) => workflow.id === createdWorkflowId);
  const workflowForNextStep = recentlyApproved ?? createdWorkflow;
  const runQuery = new URLSearchParams();
  if (workflowForNextStep) runQuery.set("workflow", workflowForNextStep.id);
  if (datasetId) runQuery.set("dataset", datasetId);
  return (
    <div>
      <PageHeader
        title="Workflow versions"
        action={
          canOperate && (
            <Link to="/workflows/new" className="btn btn-primary btn-sm">
              New workflow version
            </Link>
          )
        }
      >
        Versioned, hashed, immutable. Approval is an explicit audited action.
      </PageHeader>
      {workflowForNextStep && workflowForNextStep.status === "approved" && (
        <JourneyCue
          className="mb-6"
          action={{
            title: `${workflowForNextStep.name} v${workflowForNextStep.version} is ready`,
            description: "Choose a dataset and confirm the run size before processing documents with this version.",
            label: "Start a run",
            to: `/runs?${runQuery.toString()}`,
          }}
        />
      )}
      {createdWorkflow && createdWorkflow.status === "draft" && !recentlyApproved && (
        <output className="mb-6 block rounded-box border border-base-300 bg-base-100 px-4 py-3 text-sm">
          <strong className="block font-semibold">
            {createdWorkflow.name} v{createdWorkflow.version} was saved as a draft
          </strong>
          <span className="mt-0.5 block text-secondary">
            {canApprove
              ? "Review and approve it in the list below when it is ready for governed use."
              : "An approver must review it before it can be used in a governed run."}
          </span>
        </output>
      )}
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <TableSearch
          id="workflow-versions-search"
          className="w-full sm:max-w-sm"
          value={search}
          onChange={setSearch}
          placeholder="Workflow name or type"
        />
        <label className="flex items-center gap-2 text-sm">
          Status
          <select
            className="select border-(--border-interactive) select-sm"
            value={state.filters.status || ""}
            onChange={(e) => update({ filters: { status: e.target.value } })}
          >
            <option value="">All</option>
            <option>draft</option>
            <option>approved</option>
            <option>retired</option>
          </select>
        </label>
      </div>
      <div id="workflow-versions-table">
        <DataTable<Workflow>
          caption="Workflow versions"
          data={q.data}
          isLoading={q.isLoading}
          isFetching={q.isFetching}
          error={q.error as Error}
          onRetry={() => q.refetch()}
          state={state}
          update={update}
          getRowId={(r) => r.id}
          onRowOpen={setView}
          columns={columns}
          emptyText={
            canOperate ? (
              <span>No workflow versions yet. Create the first version to define document processing.</span>
            ) : (
              <span>No workflow versions are available in this project.</span>
            )
          }
        />
      </div>
      <ConfirmDialog
        pending={act.isPending}
        open={!!confirmation}
        title={`${confirmation?.action === "retire" ? "Retire" : "Approve"} workflow version`}
        confirmLabel={confirmation?.action === "retire" ? "Retire" : "Approve"}
        destructive={confirmation?.action === "retire"}
        reasonLabel="Reason"
        reasonRequired
        reasonHelp="This reason is recorded in the audit trail."
        onClose={() => setConfirmation(null)}
        onConfirm={(reason) => {
          if (confirmation) act.mutate({ id: confirmation.workflow.id, action: confirmation.action, reason });
        }}
        summary={
          confirmation && (
            <p>
              {confirmation.action === "retire" ? "Retire" : "Approve"} <strong>{confirmation.workflow.name}</strong> v
              {confirmation.workflow.version} (hash{" "}
              <span className="font-mono">{confirmation.workflow.content_hash.slice(7, 19)}</span>)
              {confirmation.action === "approve" ? " for production use" : " so it cannot be selected for new runs"}.
              Requires the approver role.
            </p>
          )
        }
      />
      <dialog ref={detail} className="modal" onClose={() => setView(null)} aria-label="Workflow version detail">
        {view && (
          <div className="modal-box max-w-3xl">
            <h2>
              {view.name} v{view.version}
            </h2>
            <p className="mt-2 break-all font-mono text-caption text-secondary">{view.content_hash}</p>
            <ScrollRegion label="Workflow version JSON" className="mt-3 max-h-[60vh] rounded bg-base-200 p-3">
              <pre className="font-mono text-sm leading-normal">{JSON.stringify(view.config, null, 2)}</pre>
            </ScrollRegion>
            <form method="dialog" className="modal-action">
              <button className="btn btn-outline">Close</button>
            </form>
          </div>
        )}
      </dialog>
    </div>
  );
}
