import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError } from "@/common/api/client";
import type { RunItemStatus } from "@/common/types/api";
import { Card } from "@/common/components/ui/card/card";
import { type GroupFilters, useDocumentGroups } from "../../api/get-document-groups";

/** Document identity is independent of field decisions. Boundary fixes require reprocessing. */
export function DocumentGroups({
  filters,
  reviewOnly = false,
  onLocate,
  itemStatus,
}: {
  filters: GroupFilters;
  reviewOnly?: boolean;
  itemStatus?: RunItemStatus;
  onLocate?: (unit: number) => void;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedPage = Number(searchParams.get("group_page") || 1);
  const page = Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const setPage = (nextPage: number) =>
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (nextPage === 1) next.delete("group_page");
      else next.set("group_page", String(nextPage));
      return next;
    });
  const groups = useDocumentGroups(
    { ...filters, page, ...(reviewOnly ? { review_status: "needs_review" } : {}) },
    true,
    itemStatus,
  );
  const missingPage = page > 1 && groups.error instanceof ApiError && groups.error.status === 404;
  useEffect(() => {
    if (missingPage || (groups.data && page > Math.max(1, Math.ceil(groups.data.count / 20)))) {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);
          next.delete("group_page");
          return next;
        },
        { replace: true },
      );
    }
  }, [groups.data, missingPage, page, setSearchParams]);
  const title = reviewOnly ? "Document grouping needs review" : "Identified documents";
  if (missingPage) return null;
  if (groups.isError) {
    return (
      <output className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <span>Document grouping could not be loaded.</span>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => void groups.refetch()}>
          Retry grouping
        </button>
      </output>
    );
  }
  if (!groups.data?.count) return null;
  return (
    <Card className="mb-4">
      <details open={reviewOnly || undefined}>
        <summary className="cursor-pointer font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
          {title} ({groups.data.count.toLocaleString()})
        </summary>
        <p className="mt-4 text-sm text-secondary">
          Each document has its own extracted fields. Page coverage does not confirm correct grouping.
        </p>
        <ul className="mt-4 divide-y divide-base-300">
          {groups.data.results.map((group) => (
            <li key={group.id} className="space-y-2 py-4 first:pt-0">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium [overflow-wrap:anywhere]">
                  {group.category} · Document {group.index + 1} ·{" "}
                  {group.start_unit === group.end_unit
                    ? `Page ${group.start_unit + 1}`
                    : `Pages ${group.start_unit + 1}–${group.end_unit + 1}`}
                </span>
                {onLocate ? (
                  <button type="button" className="btn btn-sm btn-ghost" onClick={() => onLocate(group.start_unit)}>
                    Locate document {group.index + 1}
                  </button>
                ) : (
                  <Link className="btn btn-sm btn-ghost" to={`/review/${group.document}?run=${group.run}&from=review`}>
                    Inspect grouping
                  </Link>
                )}
              </div>
              {reviewOnly && <p className="break-all text-sm text-secondary">{group.document_name}</p>}
              {group.review_status === "needs_review" && (
                <div className="text-sm">
                  <p className="font-medium text-warning">Grouping needs review</p>
                  <details className="mt-2">
                    <summary className="cursor-pointer text-primary">Why and how to resolve</summary>
                    <p className="mt-2 max-w-prose text-secondary">
                      {group.boundary_review_reasons?.includes("SEGMENTATION_BOUNDARY_REPAIRED")
                        ? "The proposed page ranges needed correction. "
                        : "The document boundaries or category could not be confirmed. "}
                      Check the source pages and ask an operator to adjust the workflow and reprocess. Accepting a field
                      or classification does not approve this grouping.
                    </p>
                  </details>
                </div>
              )}
            </li>
          ))}
        </ul>
        {groups.data.count > 20 && (
          <nav aria-label="Document grouping pages" className="mt-4 flex flex-wrap items-center gap-2">
            <button
              className="btn btn-sm btn-outline"
              type="button"
              disabled={page === 1 || groups.isFetching}
              onClick={() => setPage(page - 1)}
            >
              Previous groups
            </button>
            <span className="text-sm tabular-nums">
              Page {page} of {Math.ceil(groups.data.count / 20)}
            </span>
            <button
              className="btn btn-sm btn-outline"
              type="button"
              disabled={page * 20 >= groups.data.count || groups.isFetching}
              onClick={() => setPage(page + 1)}
            >
              Next groups
            </button>
          </nav>
        )}
      </details>
    </Card>
  );
}
