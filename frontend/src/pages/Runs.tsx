import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, list, post, tableParams } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { Dataset, Run, Workflow } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { AsyncButton, Card, PageHeader, StatusChip, TableSearch, fmtDate } from "@/components/ui";
import { useDebouncedSearch, useTableState } from "@/hooks/useTableState";
import { usePrefs } from "@/store/prefs";

export function Runs() {
  const { user } = useSession();
  const canOperate = !!user?.roles.includes("docai_operators");
  const { projectId, datasetId } = usePrefs();
  const nav = useNavigate(); const qc = useQueryClient();
  const { state, update } = useTableState(["status"]);
  const [search, setSearch] = useDebouncedSearch(state.q, (value) => update({ q: value }));
  const q = useQuery({ queryKey: ["runs", projectId, datasetId, state], queryFn: () => list<Run>("/runs/", { ...tableParams(state), ...(projectId ? { project: projectId } : {}), ...(datasetId ? { dataset: datasetId } : {}) }), refetchInterval: 10000 });
  const wfs = useQuery({ queryKey: ["workflows", projectId, "all"], enabled: !!projectId, queryFn: () => list<Workflow>("/workflows/", { page_size: 200, project: projectId, status__in: "draft,approved" }) });
  const dss = useQuery({ queryKey: ["datasets", projectId], enabled: !!projectId, queryFn: () => list<Dataset>("/datasets/", { page_size: 200, project: projectId }) });
  const [wf, setWf] = useState(""); const [ds, setDs] = useState(datasetId ?? ""); const [name, setName] = useState(""); const [sample, setSample] = useState("");
  const create = useMutation({ mutationFn: () => post<Run>("/runs/", { project: projectId, workflow: wf, dataset: ds, name, sample_size: sample ? Number(sample) : undefined, execute: true }),
    onSuccess: (r) => { toast.success(`Run ${r.status}`); qc.invalidateQueries({ queryKey: ["runs"] }); nav(`/runs/${r.id}`); }, onError: (e: ApiError) => toast.error(`${e.message} (${e.code})`) });
  return (
    <div>
      <PageHeader title="Runs">Every run snapshots its configuration (hash), prompt and schema versions, and adapters.</PageHeader>
      {projectId && canOperate && (
        <Card title="Start a run" className="mb-6">
          <form className="grid items-start gap-4 sm:grid-cols-2 xl:grid-cols-4" onSubmit={(e) => { e.preventDefault(); if (!wf || !ds) { toast.error("Choose a workflow and a dataset."); return; } create.mutate(); }}>
            <div className="fieldset min-w-0 gap-2 p-0 text-sm"><label className="label whitespace-normal font-medium text-base-content" htmlFor="runs-workflow">Workflow</label><select id="runs-workflow" className="select border-(--border-interactive) w-full" value={wf} onChange={(e) => setWf(e.target.value)} required><option value="">Select…</option>{wfs.data?.results.map((w) => <option key={w.id} value={w.id}>{w.name} v{w.version} ({w.status})</option>)}</select></div>
            <div className="fieldset min-w-0 gap-2 p-0 text-sm"><label className="label whitespace-normal font-medium text-base-content" htmlFor="runs-dataset">Dataset</label><select id="runs-dataset" className="select border-(--border-interactive) w-full" value={ds} onChange={(e) => setDs(e.target.value)} required><option value="">Select…</option>{dss.data?.results.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.split}, {d.document_count})</option>)}</select></div>
            <div className="fieldset min-w-0 gap-2 p-0 text-sm"><label className="label whitespace-normal font-medium text-base-content" htmlFor="runs-name">Name</label><input id="runs-name" className="input border-(--border-interactive) w-full" value={name} onChange={(e) => setName(e.target.value)} /></div>
            <div className="fieldset min-w-0 gap-2 p-0 text-sm"><label className="label whitespace-normal font-medium text-base-content" htmlFor="runs-sample">Sample (docs)</label><input id="runs-sample" className="input border-(--border-interactive) w-full" type="number" min={1} value={sample} onChange={(e) => setSample(e.target.value)} aria-describedby="sample-help" /><span id="sample-help" className="text-caption text-secondary">Blank = whole dataset</span></div>
            <div className="col-span-full"><AsyncButton type="submit" className="btn btn-primary" pending={create.isPending} pendingLabel="Starting…">Start run</AsyncButton></div>
          </form>
        </Card>)}
      <div className="mb-3 flex flex-wrap items-end gap-3"><TableSearch id="runs-search" className="w-full sm:max-w-sm" value={search} onChange={setSearch} placeholder="Run, workflow, dataset, or hash" /><label className="flex items-center gap-2 text-sm">Status<select className="select border-(--border-interactive) select-sm" value={state.filters.status || ""} onChange={(e) => update({ filters: { status: e.target.value } })}><option value="">All</option>{["queued", "running", "succeeded", "partial", "failed", "cancelled"].map((s) => <option key={s}>{s}</option>)}</select></label></div>
      <DataTable<Run> caption="Runs" data={q.data} isLoading={q.isLoading} isFetching={q.isFetching} error={q.error as Error} onRetry={() => q.refetch()} state={state} update={update} getRowId={(r) => r.id} onRowOpen={(r) => nav(`/runs/${r.id}`)}
        columns={[{ id: "name", header: "Run", accessorFn: (r) => r.name || r.workflow_name }, { id: "workflow__name", header: "Workflow", accessorFn: (r) => `${r.workflow_name}`, enableSorting: false },
                  { id: "status", header: "Status", accessorKey: "status", cell: (c) => <StatusChip status={c.getValue<string>()} /> },
                  { id: "total_items", meta: { numeric: true }, header: "Progress", accessorFn: (r) => r, enableSorting: true, cell: (c) => { const r = c.getValue<Run>(); return <span className="tabular-nums">{r.processed_items}/{r.total_items}{r.failed_items ? ` (${r.failed_items} failed)` : ""}</span>; } },
                  { id: "llm_adapter", header: "Adapters", enableSorting: false, accessorFn: (r) => `${r.layout_adapter} / ${r.llm_adapter}`, cell: (c) => <span className="font-mono text-caption">{c.getValue<string>()}</span> },
                  { id: "created", header: "Created", accessorKey: "created", cell: (c) => fmtDate(c.getValue<string>()) }]} />
    </div>
  );
}
