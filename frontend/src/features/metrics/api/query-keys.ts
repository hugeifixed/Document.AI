import type { ProcessingFilters, UsageFilters } from "../types/filters";
export const metricsKeys = {
  all: ["metrics"] as const,
  overview: (filters: ProcessingFilters) => [...metricsKeys.all, "overview", filters] as const,
  usage: (filters: UsageFilters) => [...metricsKeys.all, "usage", filters] as const,
};
