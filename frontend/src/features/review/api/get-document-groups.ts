import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { list } from "@/common/api/client";
import type { RunItemStatus, Segment } from "@/common/types/api";
import { reviewKeys } from "./query-keys";

export type GroupFilters = {
  document?: string;
  run?: string;
  project?: string;
  dataset?: string;
  review_status?: string;
  page?: number;
};

export function getDocumentGroups(filters: GroupFilters, signal?: AbortSignal) {
  return list<Segment>("/segments/", { ...filters, page_size: 20 }, { signal });
}

export function useDocumentGroups(filters: GroupFilters, enabled = true, itemStatus?: RunItemStatus) {
  const active = itemStatus === "queued" || itemStatus === "running";
  const wasActive = useRef(active);
  const query = useQuery({
    queryKey: reviewKeys.groups(filters),
    queryFn: ({ signal }) => getDocumentGroups(filters, signal),
    enabled,
    refetchInterval: active ? 3000 : false,
  });
  const { refetch } = query;
  useEffect(() => {
    // Publication can land after the final interval and before the terminal item
    // response. Refresh once on that transition before stopping observation.
    if (wasActive.current && !active && enabled) void refetch();
    wasActive.current = active;
  }, [active, enabled, refetch]);
  return query;
}
