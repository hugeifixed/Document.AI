import { Fragment, useEffect, useRef, useState } from "react";
import { useRunWorkspaceScope } from "@/workspace/navigation";
import { authorizedQueryData } from "@/workspace/context";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { announce } from "@/a11y/announce";
import { ApiError } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { FieldMetrics, LLMUsageSummary, PromptVersionReference, RunMetrics } from "@/api/types";
import { ErrorNotice } from "@/components/ErrorNotice";
import { RunProgress } from "@/components/RunProgress";
import { RunItemsTable } from "@/components/RunItemsTable";
import { useTableState } from "@/hooks/useTableState";
import { JourneyCue } from "@/components/JourneyCue";
import { promptStageLabel, PromptVersionDialog } from "@/components/PromptVersionDialog";
import { AsyncButton, Breadcrumbs, Card, fmtPct, PageHeader, ScrollRegion, StatusChip } from "@/components/ui";
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

function UsageValue({ label, value, detail }: { label: string; value: number; detail?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-sm font-medium text-secondary">{label}</dt>
      <dd className="mt-1 text-xl font-semibold lining-nums tabular-nums">{value.toLocaleString()}</dd>
      {detail && <dd className="text-caption text-(--color-ink-3)">{detail}</dd>}
    </div>
  );
}

function signalCounts(values: Record<string, number>, excluded: string[] = []) {
  return Object.entries(values)
    .filter(([name, count]) => name && count > 0 && !excluded.includes(name))
    .map(([name, count]) => `${name.replace(/_/g, " ")} ${count.toLocaleString()}`)
    .join(" · ");
}

function tokenUsageTotal(usage: LLMUsageSummary | undefined, hasError: boolean) {
  if (hasError) return "Token usage unavailable";
  if (!usage) return "Loading token usage…";
  if (usage.calls === 0) return "No reported token usage";
  if (usage.measured_calls === 0) return "Token count not reported";
  const total = `${usage.total_tokens.toLocaleString()} tokens`;
  return usage.measured_calls < usage.calls ? `${total} · Partial count` : total;
}

function ModelUsage({ usage, adapter }: { usage: LLMUsageSummary | undefined; adapter: string }) {
  if (!usage) return <output className="block text-sm text-secondary">Loading token usage…</output>;
  if (usage.calls === 0)
    return (
      <p className="reading-copy text-secondary">
        No provider token usage was recorded. Local mock runs and runs completed before usage tracking remain empty.
      </p>
    );
  const finishReasons = signalCounts(usage.finish_reasons);
  const safetyOutcomes = signalCounts(usage.safety_outcomes, ["unknown"]);
  return (
    <>
      <p className="reading-copy mb-4 text-secondary">
        Provider-reported usage for {adapter}. Cached tokens are included in input totals and reasoning tokens are
        included in output totals.
      </p>
      <dl className="mb-4 grid grid-cols-2 gap-4 md:grid-cols-4">
        <UsageValue label="Model calls" value={usage.calls} />
        <UsageValue
          label="Input tokens"
          value={usage.input_tokens}
          detail={usage.cached_input_tokens ? `${usage.cached_input_tokens.toLocaleString()} cached` : undefined}
        />
        <UsageValue
          label="Output tokens"
          value={usage.output_tokens}
          detail={usage.reasoning_tokens ? `${usage.reasoning_tokens.toLocaleString()} reasoning` : undefined}
        />
        <UsageValue label="Total tokens" value={usage.total_tokens} />
      </dl>
      {usage.measured_calls < usage.calls && (
        <p className="alert alert-soft alert-warning mb-4 text-sm">
          {usage.calls - usage.measured_calls} provider response
          {usage.calls - usage.measured_calls === 1 ? " has" : "s have"} no reported token count.
        </p>
      )}
      {(finishReasons || safetyOutcomes) && (
        <dl className="mb-4 grid gap-2 text-sm text-secondary sm:grid-cols-2">
          {finishReasons && (
            <div>
              <dt className="font-medium text-base-content">Finish reasons</dt>
              <dd className="capitalize">{finishReasons}</dd>
            </div>
          )}
          {safetyOutcomes && (
            <div>
              <dt className="font-medium text-base-content">Safety outcomes</dt>
              <dd className="capitalize">{safetyOutcomes}</dd>
            </div>
          )}
        </dl>
      )}
      <ScrollRegion label="LLM token usage breakdown">
        <table className="table table-sm">
          <caption className="sr-only">LLM token usage by workflow stage</caption>
          <thead>
            <tr>
              <th scope="col">Stage</th>
              <th scope="col" className="text-end">
                Calls
              </th>
              <th scope="col" className="text-end">
                Input
              </th>
              <th scope="col" className="text-end">
                Output
              </th>
              <th scope="col" className="text-end">
                Total
              </th>
            </tr>
          </thead>
          <tbody>
            {usage.by_stage.map((stage) => (
              <tr key={stage.stage}>
                <th scope="row" className="font-normal capitalize">
                  {stage.stage.replace(/_/g, " ")}
                </th>
                <td className="text-end tabular-nums">{stage.calls.toLocaleString()}</td>
                <td className="text-end tabular-nums">{stage.input_tokens.toLocaleString()}</td>
                <td className="text-end tabular-nums">{stage.output_tokens.toLocaleString()}</td>
                <td className="text-end font-medium tabular-nums">{stage.total_tokens.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>
    </>
  );
}

export function RunDetail() {
  const { user } = useSession();
  const canOperate = !!user?.roles.includes("docai_operators");
  const canInspectPrompts = !!user?.roles.some((role) => ["docai_operators", "docai_approvers"].includes(role));
  const [selectedPrompt, setSelectedPrompt] = useState<{
    stage: string;
    reference: PromptVersionReference;
  } | null>(null);
  const { id } = useParams();
  const { state, update } = useTableState(["status", "status__in"], { pageSize: 50, sort: "created" });
  const { run, progress, items, usage, action, progressReceipt } = useRunLifecycle(id, canOperate, state);
  const selectedFilter = state.filters.status__in || state.filters.status || "";
  const filterItems = (status: string, focusTable = false) => {
    update({
      page: 1,
      filters: { status: status.includes(",") ? "" : status, status__in: status.includes(",") ? status : "" },
    });
    if (focusTable) document.getElementById("run-items")?.focus();
  };
  useRunWorkspaceScope(run.data?.id === id ? authorizedQueryData(run) : undefined);
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
  const revoked = [run.error, progress.error, items.error].find(
    (error) => error instanceof ApiError && [401, 403, 404].includes(error.status),
  );
  if (revoked)
    return (
      <ErrorNotice
        message={revoked.message}
        onRetry={() => {
          void run.refetch();
          void progress.refetch();
          void items.refetch();
        }}
      />
    );
  if (run.error && !r) return <ErrorNotice message={run.error.message} onRetry={() => void run.refetch()} />;
  if (!r) return <output className="block">Loading…</output>;
  const failed = progress.data?.failed ?? r.failed_items;
  const availableActions = runActionsFor(r, failed);
  const nextAction = nextRunAction(r, user?.roles ?? []);
  const usedPrompts = r.used_prompt_versions ?? {};
  const hasUsedPrompts = Object.keys(usedPrompts).length > 0;
  const displayedPrompts = hasUsedPrompts ? usedPrompts : r.prompt_versions;
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
                Retry {failed.toLocaleString()} failed
              </AsyncButton>
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
      <RunProgress
        key={`progress-${r.id}`}
        run={r}
        progress={progress.data}
        receipt={progressReceipt}
        selectedFilter={selectedFilter}
        onFilter={filterItems}
        refreshing={progress.isFetching}
        error={progress.isError}
        onRefresh={() => {
          void progress.refetch();
          void run.refetch();
          void items.refetch();
        }}
      />
      <RunItemsTable
        runId={r.id}
        data={items.data}
        loading={items.isLoading}
        fetching={items.isFetching}
        error={items.error}
        onRetry={() => void items.refetch()}
        state={state}
        update={update}
        selectedFilter={selectedFilter}
        onFilter={filterItems}
        canOperate={canOperate}
        usage={usage.isError ? undefined : usage.data}
      />
      {nextAction && <JourneyCue action={nextAction} className="mb-6" />}
      <div className="mb-6 grid gap-4 md:grid-cols-2">
        <Card title={hasUsedPrompts ? "Prompts used" : "Prompt versions captured"}>
          <p className="mb-3 text-sm text-secondary">
            {hasUsedPrompts
              ? "Immutable prompt templates recorded by this run's model calls."
              : "No prompt call was recorded. These versions were captured when the run started."}
          </p>
          <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
            {Object.entries(displayedPrompts).map(([k, v]) => (
              <Fragment key={k}>
                <dt className="text-secondary">{promptStageLabel(k)}</dt>
                <dd className="min-w-0 font-mono [overflow-wrap:anywhere]">
                  {canInspectPrompts ? (
                    <button
                      type="button"
                      className="link link-primary rounded-sm text-start underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-2"
                      aria-haspopup="dialog"
                      onClick={() => setSelectedPrompt({ stage: k, reference: v })}
                    >
                      {v.name}@{v.version}
                    </button>
                  ) : (
                    `${v.name}@${v.version}`
                  )}
                </dd>
              </Fragment>
            ))}
          </dl>
        </Card>
        <Card title="Workflow warnings">
          {r.warnings.length === 0 ? (
            <p className="text-sm text-secondary">No workflow warnings.</p>
          ) : (
            <ul className="max-h-40 list-disc overflow-auto pl-5 text-sm">
              {r.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {canOperate && (
        <details
          key={r.id}
          className="collapse collapse-arrow elevation-raised mb-6 min-w-0 overflow-visible border border-base-300 bg-base-100"
        >
          <summary className="collapse-title p-4 pe-12 sm:p-5 sm:pe-12" aria-labelledby="run-token-usage-title">
            <h2
              id="run-token-usage-title"
              className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 text-section-title"
            >
              <span>LLM token usage</span>
              <span className="text-sm font-medium text-secondary tabular-nums">
                {tokenUsageTotal(usage.data, !!usage.error)}
              </span>
            </h2>
          </summary>
          <div className="collapse-content px-4 sm:px-5">
            {usage.error ? (
              <ErrorNotice message="LLM token usage could not be loaded." onRetry={() => void usage.refetch()} />
            ) : (
              <ModelUsage usage={usage.isError ? undefined : usage.data} adapter={r.llm_adapter} />
            )}
          </div>
        </details>
      )}
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
      {canInspectPrompts && (
        <PromptVersionDialog
          stage={selectedPrompt?.stage ?? null}
          reference={selectedPrompt?.reference ?? null}
          onClose={() => setSelectedPrompt(null)}
        />
      )}
    </div>
  );
}
