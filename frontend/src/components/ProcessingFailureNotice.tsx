import { ExclamationTriangleIcon } from "@heroicons/react/20/solid";
import { Link } from "react-router-dom";
import type { RunItem } from "@/api/types";

const STAGE_LABELS: Record<string, string> = {
  layout: "Layout analysis",
  workflow: "Document workflow",
  persist: "Saving results",
  dispatch_failed: "Task dispatch",
  delivery_limit: "Worker delivery",
  retry_wait: "Waiting to retry",
};

function stageLabel(stage: string) {
  return STAGE_LABELS[stage] ?? stage.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

export function ProcessingFailureNotice({ item }: { item: RunItem }) {
  return (
    <section
      role="alert"
      aria-labelledby="document-processing-failure-title"
      className="alert alert-error alert-vertical mb-4 items-start text-left lg:alert-horizontal"
    >
      <ExclamationTriangleIcon className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="document-processing-failure-title" className="text-base font-semibold">
            Document processing failed
          </h2>
          {item.error_code && (
            <span className="badge badge-sm border-current bg-transparent font-mono text-current">
              {item.error_code}
            </span>
          )}
        </div>
        <p className="mt-1 break-words text-sm">
          {item.error_message || "No additional failure details were recorded."}
        </p>
        <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm">
          <div className="flex gap-1">
            <dt className="font-semibold">Scope:</dt>
            <dd>Entire document for this run</dd>
          </div>
          {item.stage && (
            <div className="flex gap-1">
              <dt className="font-semibold">Stage:</dt>
              <dd>{stageLabel(item.stage)}</dd>
            </div>
          )}
          <div className="flex gap-1">
            <dt className="font-semibold">Attempts:</dt>
            <dd className="tabular-nums">{item.attempts}</dd>
          </div>
          {item.correlation_id && (
            <div className="flex min-w-0 gap-1">
              <dt className="font-semibold">Trace:</dt>
              <dd className="break-all font-mono">{item.correlation_id}</dd>
            </div>
          )}
        </dl>
        {item.retryable && <p className="mt-2 text-sm font-medium">This failure is marked as retryable.</p>}
      </div>
      <Link className="btn btn-sm btn-outline shrink-0" to={`/runs/${item.run}`}>
        View run
      </Link>
    </section>
  );
}
