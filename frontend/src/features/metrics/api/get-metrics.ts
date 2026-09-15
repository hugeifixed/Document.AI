import { useQuery } from "@tanstack/react-query";
import { get } from "@/common/api/client";
import type { Metrics } from "@/common/types/api";
import type { ProcessingFilters } from "../types/filters";
import { metricsKeys } from "./query-keys";
export function getMetrics(filters: ProcessingFilters, signal?: AbortSignal) {
  return get<Metrics>("/metrics/", { ...filters }, { signal });
}
export function useMetrics(filters: ProcessingFilters, enabled = true) {
  return useQuery({
    queryKey: metricsKeys.overview(filters),
    queryFn: ({ signal }) => getMetrics(filters, signal),
    enabled,
    staleTime: 60_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    placeholderData: undefined,
  });
}
