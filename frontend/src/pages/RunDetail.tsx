import { Fragment, useEffect, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { announce } from "@/a11y/announce";
import { ApiError } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { FieldMetrics, RunMetrics } from "@/api/types";
import { ErrorNotice } from "@/components/ErrorNotice";
import { JourneyCue } from "@/components/JourneyCue";
import { AsyncButton, Breadcrumbs, Card, fmtDate, fmtPct, PageHeader, Stat, StatusChip } from "@/components/ui";
import { nextRunAction } from "@/journey/guidance";
import { type RunAction, runActionsFor, useRunLifecycle } from "@/runs/lifecycle";

function MetricRow({ name, m }: { name: string; m: FieldMetrics }) {
  return (
    <tr>
      <th scope="row" className="font-normal">
        {name}
      </th>
      <td className="tabular-nums">{m.support}</td>
      <td className="tabular-nums text-success">{m.match}</td>
      <td className="tabular-nums">{m.mismatch}</td>
      <td className="tabular-nums">{m.missing}</td>
      <td className="tabular-nums">{m.spurious}</td>
      <td className="tabular-nums">{m.true_blank}</td>
      <td className="tabular-nums">{fmtPct(m.precision)}</td>
      <td className="tabular-nums">{fmtPct(m.recall)}</td>
      <td className="tabular-nums">{fmtPct(m.f1)}</td>
      <td className="tabular-nums">{fmtPct(m.specificity)}</td>
    </tr>
  );
}

export function RunDetail() {
  const { user } = useSession();
  const canOperate = !!user?.roles.includes("docai_operators");
  const { id } = useParams();
  const { run, progress, items, action } = useRunLifecycle(id);
  const last = useRef<string | undefined>(undefined);
  useEffect(() => {
    const s = run.data?.status;
    if (s && last.current && last.current !== s) announce(`Run ${s}`);
    last.current = s;
  }, [run.data?.status]);
  const requestAction = (requested: RunAction) =>
    action.mutate(requested, {
      onSuccess: (updated) =>
        toast.success(
          requested === "cancel"
            ? updated.status === "cancelled"
              ? "Run cancelled"
              : "Cancellation requested"
            : `Run ${requested} requested`,
        ),
      onError: (error) => {
        const detail = error as ApiError;
        toast.error(`${detail.message} (${detail.code})`);
      },
    });
  const r = run.data;
  const m: RunMetrics | undefined = r?.metrics;
  if (run.error) return <ErrorNotice message={run.error.message} onRetry={() => void run.refetch()} />;
  if (!r) return <output className="block">Loading…</output>;
  const failed = items.data?.results.filter((i) => i.status === "failed") ?? [];
  const availableActions = runActionsFor(r, failed.length);
  const nextAction = nextRunAction(r, user?.roles ?? []);
  return (
    <div>
      <Breadcrumbs items={[{ label: "Runs", to: "/runs" }, { label: r.name || r.workflow_name }]} />
      <PageHeader
        title={r.name || r.workflow_name}
        action={
          <div className="flex flex-wrap gap-2">
            {canOperate && availableActions.canCancel && (
              <AsyncButton
                className="btn btn-sm btn-outline"
                pending={action.isPending && action.variables === "cancel"}
                pendingLabel="Cancelling…"
                disabled={action.isPending}
                onClick={() => requestAction("cancel")}
              >
                Cancel run
              </AsyncButton>
            )}
            {canOperate && availableActions.canRetry && (
              <AsyncButton
                className="btn btn-sm btn-outline"
                pending={action.isPending && action.variables === "retry"}
                pendingLabel="Retrying…"
                disabled={action.isPending}
                onClick={() => requestAction("retry")}
              >
                Retry {failed.length} failed
              </AsyncButton>
            )}
            {r.guidance?.export_ready && (
              <Link className="btn btn-sm btn-outline" to={`/exports?run=${r.id}`}>
                Export
              </Link>
            )}
          </div>
        }
      >
        <StatusChip status={r.status} />
        <span>
          {r.workflow_name} · {r.workflow_type}
        </span>
        <span>dataset {r.dataset_name}</span>
        <span className="font-mono" title={r.config_hash}>
          hash {r.config_hash.slice(7, 19)}
        </span>
        <span className="font-mono">
          {r.layout_adapter} / {r.llm_adapter}
          {r.model_deployment ? ` / ${r.model_deployment}` : ""}
        </span>
      </PageHeader>
      {availableActions.cancellationPending && (
        <output className="alert alert-warning alert-soft mb-6">
          <span className="loading loading-spinner loading-sm" aria-hidden="true" />
          <span>
            <strong className="block font-semibold">Cancellation requested</strong>
            <span className="block text-sm">
              Active documents will finish safely. Documents that have not started are being skipped.
            </span>
          </span>
        </output>
      )}
      {nextAction && <JourneyCue action={nextAction} className="mb-6" />}
      <div className="mb-6 grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Stat label="Documents" value={r.total_items} />
        <Stat
          label="Processed"
          value={r.processed_items}
          hint={r.failed_items ? `${r.failed_items} failed` : undefined}
        />
        <Stat label="Started" value={<span className="text-base">{fmtDate(r.started_at)}</span>} />
        <Stat label="Finished" value={<span className="text-base">{fmtDate(r.finished_at)}</span>} />
      </div>
      {r.status === "running" && progress.data && (
        <div className="mb-6">
          <progress
            className="progress progress-primary w-full"
            value={progress.data.total - progress.data.remaining}
            max={progress.data.total}
            aria-label="Run progress"
          />
          <p className="text-sm tabular-nums">
            {progress.data.total - progress.data.remaining}/{progress.data.total} · stage {progress.data.stage}
            {progress.data.estimated_seconds_remaining != null
              ? ` · ~${progress.data.estimated_seconds_remaining}s remaining`
              : ""}
          </p>
        </div>
      )}
      <div className="mb-6 grid gap-4 md:grid-cols-2">
        <Card title="Versions used">
          <dl className="grid grid-cols-2 gap-1 text-sm">
                {Object.entries(r.prompt_versions).map(([k, v]) => (
                  <Fragment key={k}>
                    <dt className="text-secondary">
                      {k} prompt
                    </dt>
                    <dd className="font-mono">
                      {v.name}@{v.version}
                    </dd>
                  </Fragment>
                ))}
          </dl>
        </Card>
        <Card title="Warnings">
          {r.warnings.length === 0 ? (
            <p className="text-sm text-secondary">None.</p>
          ) : (
            <ul className="max-h-40 list-disc overflow-auto pl-5 text-sm">
              {r.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {m?.extraction && (
        <Card title="Extraction metrics (against final ground truth)" className="mb-6">
          <p className="reading-copy mb-2 text-secondary">
            Per-field outcomes: match, mismatch, missing (FN), spurious (hallucinated, FP), true blank (TN). Precision
            counts mismatches against the model. Graded documents:{" "}
            {m.extraction.aggregate.support
              ? ((m.extraction as unknown as { graded_documents?: number }).graded_documents ?? "—")
              : "—"}
            .
          </p>
          <div className="overflow-x-auto">
            <table className="table table-sm table-metrics">
              <caption className="sr-only">Extraction metrics per field</caption>
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">n</th>
                  <th scope="col">Match</th>
                  <th scope="col">Mismatch</th>
                  <th scope="col">Missing</th>
                  <th scope="col">Spurious</th>
                  <th scope="col">True blank</th>
                  <th scope="col">Precision</th>
                  <th scope="col">Recall</th>
                  <th scope="col">F1</th>
                  <th scope="col">Specificity</th>
                </tr>
              </thead>
              <tbody>
                <MetricRow name="All fields" m={m.extraction.aggregate} />
                {Object.entries(m.extraction.per_field).map(([k, v]) => (
                  <MetricRow key={k} name={k} m={v} />
                ))}
              </tbody>
            </table>
          </div>
          {m.extraction.out_of_schema_labels && Object.keys(m.extraction.out_of_schema_labels).length > 0 && (
            <p className="mt-2 text-caption">
              Labeled but not produced by this workflow (reported, not graded):{" "}
              {Object.entries(m.extraction.out_of_schema_labels)
                .map(([k, v]) => `${k} (${v})`)
                .join(", ")}
            </p>
          )}
        </Card>
      )}
      {m?.classification && (
        <Card title="Classification" className="mb-6">
          <p className="mb-2 text-sm">
            Accuracy <span className="tabular-nums">{fmtPct(m.classification.accuracy)}</span> · macro F1{" "}
            <span className="tabular-nums">{fmtPct(m.classification.macro.f1)}</span> · micro F1{" "}
            <span className="tabular-nums">{fmtPct(m.classification.micro.f1)}</span> · weighted F1{" "}
            <span className="tabular-nums">{fmtPct(m.classification.weighted.f1)}</span> · other/unclassified{" "}
            <span className="tabular-nums">{fmtPct(m.classification.other_or_unclassified_rate)}</span>
          </p>
          <div className="overflow-x-auto">
            <table className="table table-sm table-metrics">
              <caption className="sr-only">Confusion matrix: rows are truth, columns are predictions</caption>
              <thead>
                <tr>
                  <th scope="col">Truth ↓ / Predicted →</th>
                  {m.classification.labels.map((l) => (
                    <th key={l} scope="col">
                      {l}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {m.classification.matrix.map((row, i) => (
                  <tr key={i}>
                    <th scope="row" className="font-normal">
                      {m.classification!.labels[i]}
                    </th>
                    {row.map((v, j) => (
                      <td
                        key={j}
                        className={`tabular-nums ${i === j && v ? "font-semibold text-success" : v ? "text-error" : ""}`}
                      >
                        {v}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {m?.segmentation && (
        <Card title="Segmentation" className="mb-6">
          <dl className="grid grid-cols-2 gap-1 text-sm md:grid-cols-4">
            {Object.entries(m.segmentation.aggregate).map(([k, v]) => (
              <div key={k}>
                <dt className="text-secondary">{k.replace(/_/g, " ")}</dt>
                <dd className="tabular-nums">
                  {typeof v === "number" && v <= 1 && !k.includes("count") && !k.includes("docs")
                    ? fmtPct(v)
                    : String(v)}
                </dd>
              </div>
            ))}
          </dl>
        </Card>
      )}
      {m?.quality_indicators && (
        <Card title="Quality indicators (no ground truth)" className="mb-6">
          <p className="reading-copy mb-2 text-secondary">{m.quality_indicators.note}</p>
          <div className="overflow-x-auto">
            <table className="table table-sm table-metrics">
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">Non-blank</th>
                  <th scope="col">Low score</th>
                  <th scope="col">Grounded</th>
                  <th scope="col">Validation failures</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(m.quality_indicators.per_field).map(([k, v]) => (
                  <tr key={k}>
                    <th scope="row" className="font-normal">
                      {k}
                    </th>
                    <td className="tabular-nums">{fmtPct(v.non_blank_rate as number)}</td>
                    <td className="tabular-nums">{fmtPct(v.low_score_rate as number)}</td>
                    <td className="tabular-nums">{fmtPct(v.grounding_rate as number)}</td>
                    <td className="tabular-nums">{fmtPct(v.validation_failure_rate as number)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      <div id="run-items">
        <Card title={`Items (${items.data?.count ?? "…"})`}>
          <div className="overflow-x-auto">
            <table className="table table-sm">
              <caption className="sr-only">Run items</caption>
              <thead>
                <tr>
                  <th scope="col">Document</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="text-end">
                    Attempts
                  </th>
                  <th scope="col" className="text-end">
                    Duration
                  </th>
                  <th scope="col">Error</th>
                </tr>
              </thead>
              <tbody>
                {items.data?.results.map((i) => (
                  <tr key={i.id}>
                    <td>
                      <Link className="link link-primary" to={`/documents/${i.document}?run=${r.id}&from=run`}>
                        {i.document_name}
                      </Link>
                    </td>
                    <td>
                      <StatusChip status={i.status} />
                    </td>
                    <td className="text-end lining-nums tabular-nums">{i.attempts}</td>
                    <td className="text-end lining-nums tabular-nums">
                      {i.duration_ms != null ? `${i.duration_ms} ms` : "—"}
                    </td>
                    <td className="text-sm">
                      {i.error_code && (
                        <>
                          <span className="font-mono text-caption">{i.error_code}</span> {i.error_message}
                          {i.retryable && <span className="badge badge-ghost badge-sm ml-1">retryable</span>}
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}
