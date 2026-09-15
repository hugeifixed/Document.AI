import { useQuery } from "@tanstack/react-query";
import { get } from "@/common/api/client";
import type { MetricsUsage } from "@/common/types/api";
import type { UsageFilters } from "../types/filters";
import { metricsKeys } from "./query-keys";
export function getMetricsUsage(filters: UsageFilters, signal?: AbortSignal) {
  return get<MetricsUsage>("/metrics/usage/", { ...filters }, { signal });
}
export function useMetricsUsage(filters: UsageFilters, enabled = true) {
  return useQuery({
    queryKey: metricsKeys.usage(filters),
    queryFn: ({ signal }) => getMetricsUsage(filters, signal),
    enabled,
    staleTime: 60_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    placeholderData: undefined,
  });
}
