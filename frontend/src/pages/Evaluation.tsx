import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, list, post, tableParams } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { Evaluation, Run } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { AsyncButton, Card, Field, PageHeader, fmtDate, fmtPct } from "@/components/ui";
import { useTableState } from "@/hooks/useTableState";
import { usePrefs } from "@/store/prefs";

export function EvaluationPage() {
  const { user } = useSession();
  const canOperate = !!user?.roles.includes("docai_operators");
  const projectId = usePrefs((s) => s.projectId); const qc = useQueryClient();
  const { state, update } = useTableState([]);
  const q = useQuery({ queryKey: ["evaluations", projectId, state], queryFn: () => list<Evaluation>("/evaluations/", { ...tableParams(state), ...(projectId ? { project: projectId } : {}) }) });
  const runs = useQuery({ queryKey: ["runs", projectId, "done"], queryFn: () => list<Run>("/runs/", { page_size: 100, status__in: "succeeded,partial", ...(projectId ? { project: projectId } : {}) }) });
  const [run, setRun] = useState(""); const [tol, setTol] = useState("0.01");
  const create = useMutation({ mutationFn: () => post<Evaluation>("/evaluations/", { run, numeric_tolerance: Number(tol) }), onSuccess: () => { toast.success("Evaluation created"); qc.invalidateQueries({ queryKey: ["evaluations"] }); }, onError: (e: ApiError) => toast.error(e.message) });
  return (
    <div>
      <PageHeader title="Evaluations">Metrics are computed only against final ground truth. Without it, you get quality indicators — never accuracy.</PageHeader>
      {canOperate && <Card title="Evaluate a run" className="mb-6 @container">
        <form className="grid items-start gap-x-4 gap-y-5 @min-[48rem]:grid-cols-[minmax(0,1fr)_14rem_auto]" onSubmit={(e) => { e.preventDefault(); if (run) create.mutate(); }}>
          <Field id="evaluation-run" label="Run">
            <select id="evaluation-run" className="select w-full border-(--border-interactive)" value={run} onChange={(e) => setRun(e.target.value)} required>
              <option value="">Select a run…</option>{runs.data?.results.map((r) => <option key={r.id} value={r.id}>{r.name || r.workflow_name} · {r.dataset_name}</option>)}
            </select>
          </Field>
          <Field id="evaluation-tolerance" label="Numeric tolerance">
            <input id="evaluation-tolerance" className="input w-full border-(--border-interactive)" value={tol} onChange={(e) => setTol(e.target.value)} inputMode="decimal" aria-describedby="tol-help" />
            <p id="tol-help" className="field-help text-sm text-secondary">Relative, e.g. 0.01 = 1%</p>
          </Field>
          <div className="grid gap-2"><span className="field-spacer hidden @min-[48rem]:block" aria-hidden="true" /><AsyncButton type="submit" className="btn btn-primary w-full @min-[48rem]:w-auto" pending={create.isPending} pendingLabel="Evaluating…" disabled={!run}>Evaluate</AsyncButton></div>
        </form>
      </Card>}
      <DataTable<Evaluation> caption="Evaluations" data={q.data} isLoading={q.isLoading} error={q.error as Error} onRetry={() => q.refetch()} state={state} update={update} getRowId={(r) => r.id}
        columns={[{ id: "run__name", header: "Run", enableSorting: false, accessorKey: "run_name", cell: (c) => c.row.original.run ? <Link className="link link-primary" to={`/runs/${c.row.original.run}`}>{c.getValue<string>() || "run"}</Link> : "—" },
                  { id: "has_ground_truth", header: "Ground truth", enableSorting: false, accessorKey: "has_ground_truth", cell: (c) => (c.getValue<boolean>() ? "yes" : "indicators only") },
                  { id: "f1", meta: { numeric: true }, header: "Extraction F1", enableSorting: false, accessorFn: (r) => r.metrics.extraction?.aggregate.f1, cell: (c) => <span className="tabular-nums">{fmtPct(c.getValue<number | null>())}</span> },
                  { id: "prec", meta: { numeric: true }, header: "Precision", enableSorting: false, accessorFn: (r) => r.metrics.extraction?.aggregate.precision, cell: (c) => <span className="tabular-nums">{fmtPct(c.getValue<number | null>())}</span> },
                  { id: "rec", meta: { numeric: true }, header: "Recall", enableSorting: false, accessorFn: (r) => r.metrics.extraction?.aggregate.recall, cell: (c) => <span className="tabular-nums">{fmtPct(c.getValue<number | null>())}</span> },
                  { id: "cls", meta: { numeric: true }, header: "Classification acc.", enableSorting: false, accessorFn: (r) => r.metrics.classification?.accuracy, cell: (c) => <span className="tabular-nums">{fmtPct(c.getValue<number | null>())}</span> },
                  { id: "seg", meta: { numeric: true }, header: "Segmentation F1", enableSorting: false, accessorFn: (r) => r.metrics.segmentation?.aggregate.boundary_f1, cell: (c) => <span className="tabular-nums">{fmtPct(c.getValue<number | null>())}</span> },
                  { id: "created", header: "Created", accessorKey: "created", cell: (c) => fmtDate(c.getValue<string>()) }]} />
    </div>
  );
}
