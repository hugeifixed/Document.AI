import { Field } from "@/common/components/ui/field/field";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { apiFieldError, errorMessage, get, list, post, tableParams } from "@/common/api/client";
import { useSession } from "@/auth/Session";
import type { Evaluation, Run } from "@/common/types/api";
import { DataTable } from "@/components/DataTable";
import { JourneyCue } from "@/components/JourneyCue";
import { AsyncButton, fmtDate, fmtPct } from "@/components/ui";
import { Card } from "@/common/components/ui/card/card";
import { PageHeader } from "@/common/components/ui/page-header/page-header";

import { useTableState } from "@/hooks/useTableState";
import { useRunCollection } from "@/runs/lifecycle";
import { useWorkingContext } from "@/workspace/context";

const evaluationSchema = z.object({
  run: z.string().min(1, "Choose a completed run."),
  tolerance: z
    .string()
    .min(1, "Enter a numeric tolerance.")
    .refine((value) => {
      const number = Number(value);
      return Number.isFinite(number) && number >= 0;
    }, "Enter zero or a positive decimal."),
});
type EvaluationForm = z.infer<typeof evaluationSchema>;

export function EvaluationPage() {
  const { user } = useSession();
  const canOperate = !!user?.roles.includes("docai_operators");
  const { projectId, datasetId } = useWorkingContext();
  const [searchParams] = useSearchParams();
  const requestedRun = searchParams.get("run");
  const [createdEvaluation, setCreatedEvaluation] = useState<Evaluation | null>(null);
  const qc = useQueryClient();
  const { state, update } = useTableState([]);
  const q = useQuery({
    queryKey: ["evaluations", projectId, state],
    queryFn: ({ signal }) =>
      list<Evaluation>(
        "/evaluations/",
        { ...tableParams(state), ...(projectId ? { project: projectId } : {}) },
        { signal },
      ),
  });
  const runs = useRunCollection({ purpose: "evaluation", projectId, datasetId });
  const {
    register,
    handleSubmit,
    resetField,
    setError,
    setValue,
    watch,
    formState: { errors },
  } = useForm<EvaluationForm>({
    resolver: zodResolver(evaluationSchema),
    defaultValues: { run: "", tolerance: "0.01" },
  });
  useEffect(() => {
    resetField("run", { defaultValue: "" });
    setCreatedEvaluation(null);
  }, [projectId, datasetId, resetField]);
  useEffect(() => {
    if (requestedRun && runs.data?.results.some((run) => run.id === requestedRun)) {
      setValue("run", requestedRun, { shouldValidate: false });
    }
  }, [requestedRun, runs.data, setValue]);
  const selectedRunId = watch("run");
  const selectedRun = useQuery({
    queryKey: ["run", selectedRunId],
    enabled: !!selectedRunId,
    queryFn: ({ signal }) => get<Run>(`/runs/${selectedRunId}/`, undefined, { signal }),
  });
  const create = useMutation({
    mutationFn: (values: EvaluationForm) =>
      post<Evaluation>("/evaluations/", { run: values.run, numeric_tolerance: Number(values.tolerance) }),
    onSuccess: (evaluation) => {
      toast.success("Evaluation created");
      setCreatedEvaluation(evaluation);
      qc.invalidateQueries({ queryKey: ["evaluations"] });
      qc.invalidateQueries({ queryKey: ["run", evaluation.run] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: unknown) => {
      const runError = apiFieldError(error, "run");
      const toleranceError = apiFieldError(error, "numeric_tolerance");
      if (runError) setError("run", { type: "server", message: runError });
      if (toleranceError) setError("tolerance", { type: "server", message: toleranceError });
      toast.error(errorMessage(error));
    },
  });
  return (
    <div>
      <PageHeader title="Evaluations">
        Metrics are computed only against final ground truth. Without it, you get quality indicators — never accuracy.
      </PageHeader>
      {createdEvaluation?.run && (
        <JourneyCue
          className="mb-6"
          action={{
            title: createdEvaluation.has_ground_truth
              ? "Accuracy evaluation is complete"
              : "Quality indicators are ready",
            description: "The evaluation used stored predictions and did not repeat document or model processing.",
            label: "Export this run",
            to: `/exports?run=${createdEvaluation.run}`,
          }}
        />
      )}
      {canOperate && (
        <Card title="Evaluate a run" className="mb-6 @container">
          {selectedRun.data && (
            <p className="reading-copy mb-4 text-sm text-secondary">
              {selectedRun.data.guidance?.ground_truth.labels
                ? `${selectedRun.data.guidance.ground_truth.labels.toLocaleString()} final labels are available, so this evaluation will calculate accuracy metrics.`
                : "No final labels are available for this dataset, so this evaluation will report operational quality indicators rather than accuracy."}
            </p>
          )}
          <form
            className="grid items-start gap-x-4 gap-y-5 @min-[48rem]:grid-cols-[minmax(0,1fr)_14rem_auto]"
            onSubmit={handleSubmit((values) => create.mutate(values))}
          >
            <Field id="evaluation-run" label="Run" required>
              <select
                id="evaluation-run"
                className={`select w-full border-(--border-interactive) ${errors.run ? "select-error" : ""}`}
                {...register("run")}
                required
                aria-invalid={!!errors.run}
                aria-describedby={errors.run ? "evaluation-run-error" : undefined}
              >
                <option value="">Select a run…</option>
                {runs.data?.results.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name || r.workflow_name} · {r.dataset_name}
                  </option>
                ))}
              </select>
              {errors.run && (
                <p id="evaluation-run-error" className="field-error text-sm text-error">
                  {errors.run.message}
                </p>
              )}
            </Field>
            <Field id="evaluation-tolerance" label="Numeric tolerance">
              <input
                id="evaluation-tolerance"
                className={`input w-full border-(--border-interactive) ${errors.tolerance ? "input-error" : ""}`}
                {...register("tolerance")}
                inputMode="decimal"
                aria-invalid={!!errors.tolerance}
                aria-describedby={errors.tolerance ? "evaluation-tolerance-error" : "tol-help"}
              />
              {errors.tolerance ? (
                <p id="evaluation-tolerance-error" className="field-error text-sm text-error">
                  {errors.tolerance.message}
                </p>
              ) : (
                <p id="tol-help" className="field-help text-sm text-secondary">
                  Relative, e.g. 0.01 = 1%
                </p>
              )}
            </Field>
            <div className="grid gap-2">
              <span className="field-spacer hidden @min-[48rem]:block" aria-hidden="true" />
              <AsyncButton
                type="submit"
                className="btn btn-primary w-full @min-[48rem]:w-auto"
                pending={create.isPending}
                pendingLabel="Evaluating…"
              >
                Evaluate
              </AsyncButton>
            </div>
          </form>
        </Card>
      )}
      <DataTable<Evaluation>
        caption="Evaluations"
        data={q.data}
        isLoading={q.isLoading}
        error={q.error as Error}
        onRetry={() => q.refetch()}
        state={state}
        update={update}
        getRowId={(r) => r.id}
        columns={[
          {
            id: "run__name",
            header: "Run",
            enableSorting: false,
            accessorKey: "run_name",
            cell: (c) =>
              c.row.original.run ? (
                <Link className="link link-primary" to={`/runs/${c.row.original.run}`}>
                  {c.getValue<string>() || "run"}
                </Link>
              ) : (
                "—"
              ),
          },
          {
            id: "has_ground_truth",
            header: "Ground truth",
            enableSorting: false,
            accessorKey: "has_ground_truth",
            cell: (c) => (c.getValue<boolean>() ? "yes" : "indicators only"),
          },
          {
            id: "f1",
            meta: { numeric: true },
            header: "Extraction F1",
            enableSorting: false,
            accessorFn: (r) => r.metrics.extraction?.aggregate.f1,
            cell: (c) => <span className="tabular-nums">{fmtPct(c.getValue<number | null>())}</span>,
          },
          {
            id: "prec",
            meta: { numeric: true },
            header: "Precision",
            enableSorting: false,
            accessorFn: (r) => r.metrics.extraction?.aggregate.precision,
            cell: (c) => <span className="tabular-nums">{fmtPct(c.getValue<number | null>())}</span>,
          },
          {
            id: "rec",
            meta: { numeric: true },
            header: "Recall",
            enableSorting: false,
            accessorFn: (r) => r.metrics.extraction?.aggregate.recall,
            cell: (c) => <span className="tabular-nums">{fmtPct(c.getValue<number | null>())}</span>,
          },
          {
            id: "cls",
            meta: { numeric: true },
            header: "Classification acc.",
            enableSorting: false,
            accessorFn: (r) => r.metrics.classification?.accuracy,
            cell: (c) => <span className="tabular-nums">{fmtPct(c.getValue<number | null>())}</span>,
          },
          {
            id: "seg",
            meta: { numeric: true },
            header: "Segmentation F1",
            enableSorting: false,
            accessorFn: (r) => r.metrics.segmentation?.aggregate.boundary_f1,
            cell: (c) => <span className="tabular-nums">{fmtPct(c.getValue<number | null>())}</span>,
          },
          { id: "created", header: "Created", accessorKey: "created", cell: (c) => fmtDate(c.getValue<string>()) },
        ]}
        emptyText="No evaluations are available in this project. Choose a completed run above to create the first one."
      />
    </div>
  );
}
