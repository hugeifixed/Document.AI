import { useSearchParams } from "react-router-dom";
import { ApiError } from "@/common/api/client";
import { PageHeader } from "@/common/components/ui/page-header/page-header";
import { Skeleton } from "@/common/components/ui/skeleton/skeleton";
import { usePageTitleState } from "@/common/hooks/use-page-title-state";
import { errorPageTitle } from "@/common/utils/error-page-title";
import { useMetrics } from "../api/get-metrics";
import { useMetricsUsage } from "../api/get-metrics-usage";
import { readFilters, updateFilters, utcToday, validateDates } from "../utils/filters";
import { DateFilter } from "./date-filter/date-filter";
import { ProcessingSection } from "./processing-section/processing-section";
import { ReliabilitySection } from "./reliability-section/reliability-section";
import { ReviewSection } from "./review-section/review-section";
import { UsageSection } from "./usage-section/usage-section";
export function MetricsDashboard({
  projectId,
  datasetId,
  canViewUsage,
}: {
  projectId: string | null;
  datasetId: string | null;
  canViewUsage: boolean;
}) {
  const [params, setParams] = useSearchParams();
  const { processing, usage, error } = readFilters(params, {
    project: projectId || undefined,
    dataset: datasetId || undefined,
  });
  const overview = useMetrics(processing, !error);
  const usageQuery = useMetricsUsage(usage, canViewUsage && !error);
  const denied = overview.error instanceof ApiError && overview.error.status === 403;
  usePageTitleState(denied ? errorPageTitle(overview.error) : undefined);
  const update = (changes: Record<string, string>) => setParams(updateFilters(params, changes));
  const refresh = () => {
    void overview.refetch();
    if (canViewUsage) void usageQuery.refetch();
  };
  const failure = (err: Error | null) =>
    err instanceof ApiError
      ? `${err.message} (${err.code}${err.traceId ? `; reference ${err.traceId}` : ""})`
      : err?.message || "Metrics could not be loaded.";
  return (
    <div className="space-y-6">
      <div>
        <PageHeader
          title="Metrics"
          action={
            <button
              className="btn btn-outline"
              disabled={!!error || overview.isFetching || (canViewUsage && usageQuery.isFetching)}
              onClick={refresh}
            >
              Refresh
            </button>
          }
        >
          Operational trends for the current working project and dataset.
        </PageHeader>
        <DateFilter
          key={`${processing.range}:${processing.start}:${processing.end}`}
          range={processing.range}
          start={processing.start}
          end={processing.end}
          today={utcToday()}
          error={error}
          onChange={update}
          validate={validateDates}
        />
        <p className="text-caption text-secondary">
          Updates every 60 seconds while this page is visible. Existing records are not a complete historical ledger.
        </p>
        {!error && overview.data && !overview.isError && (
          <p className="mt-2 text-caption text-secondary">
            As of{" "}
            <time dateTime={overview.data.meta.as_of}>
              {new Date(overview.data.meta.as_of).toLocaleString(undefined, { timeZone: "UTC" })} UTC
            </time>{" "}
            · {overview.data.meta.start_date}–{overview.data.meta.end_date}
          </p>
        )}
      </div>
      {!error && !denied && (
        <ProcessingSection
          data={overview.isError ? undefined : overview.data?.processing}
          documentType={processing.document_type}
          status={processing.status}
          onChange={update}
        >
          {overview.isPending && (
            <output aria-label="Loading metrics" className="space-y-4">
              <span className="sr-only">Loading metrics</span>
              <Skeleton className="h-28 w-full" />
              <div className="grid gap-4 xl:grid-cols-2">
                <Skeleton className="h-96 w-full" />
                <Skeleton className="h-96 w-full" />
              </div>
            </output>
          )}
          {overview.isError && (
            <div role="alert" className="rounded-box border border-error bg-base-100 p-4 sm:p-5">
              <h2>Metrics unavailable</h2>
              <p className="mt-2 text-secondary">{failure(overview.error)}</p>
              <button className="btn btn-outline mt-4" onClick={() => void overview.refetch()}>
                Retry metrics
              </button>
            </div>
          )}
        </ProcessingSection>
      )}
      {!error && denied && (
        <div role="alert">
          <h2>Access denied</h2>
          <p>{failure(overview.error)}</p>
        </div>
      )}
      {!error && overview.data && !overview.isError && (
        <>
          <ReliabilitySection data={overview.data.runs} />
          <ReviewSection data={overview.data.review} />
        </>
      )}
      {canViewUsage && !error && !denied && (
        <section aria-labelledby="usage-heading" className="space-y-4">
          <div>
            <h2 id="usage-heading">LLM usage</h2>
            <p className="mt-1 text-caption text-secondary">
              Operator-only recorded responses and measured token usage.
            </p>
          </div>
          <UsageSection data={usageQuery.isError ? undefined : usageQuery.data} filters={usage} onChange={update}>
            {usageQuery.isPending && (
              <output className="block" aria-label="Loading LLM usage">
                <Skeleton className="h-96 w-full" />
              </output>
            )}
            {usageQuery.isError && (
              <div role="alert">
                <p>{failure(usageQuery.error)}</p>
                <button className="btn btn-outline mt-4" onClick={() => void usageQuery.refetch()}>
                  Retry usage
                </button>
              </div>
            )}
            {usageQuery.data && !usageQuery.isError && (
              <>
                <p className="text-caption text-secondary">
                  As of{" "}
                  <time dateTime={usageQuery.data.meta.as_of}>
                    {new Date(usageQuery.data.meta.as_of).toLocaleString(undefined, { timeZone: "UTC" })} UTC
                  </time>
                </p>
              </>
            )}
          </UsageSection>
        </section>
      )}
    </div>
  );
}
