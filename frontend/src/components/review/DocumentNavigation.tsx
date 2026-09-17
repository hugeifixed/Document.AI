import { ChevronLeftIcon, ChevronRightIcon } from "@heroicons/react/20/solid";
import { Link } from "react-router-dom";
import type { DocumentNavigation as Navigation } from "@/common/types/api";

/** Browse the authorized run/dataset, independently of field selection and table pagination. */
export function DocumentNavigation({
  navigation,
  searchParams,
}: {
  navigation: Navigation;
  searchParams: URLSearchParams;
}) {
  const params = new URLSearchParams(searchParams);
  params.delete("field");
  params.delete("group_page");
  if (navigation.run) params.set("run", navigation.run);
  else params.delete("run");
  const scope = navigation.scope === "run" ? "run" : "dataset";
  const single = !navigation.previous && !navigation.next;
  const buttonClass = "btn btn-sm btn-outline min-h-11 sm:min-h-10";
  return (
    <nav aria-label="Document navigation" className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <span className="text-caption text-secondary">
        {single ? `Only document in this ${scope}` : `Documents in this ${scope} · Newest uploads first`}
      </span>
      <div className="flex items-center gap-2">
        {navigation.previous ? (
          <Link
            className={buttonClass}
            to={`/documents/${navigation.previous.id}?${params}`}
            aria-label={`Previous document: ${navigation.previous.original_filename}`}
            title={navigation.previous.original_filename}
          >
            <ChevronLeftIcon className="size-4" aria-hidden /> Previous
          </Link>
        ) : (
          <button type="button" className={buttonClass} disabled aria-label="Previous document">
            <ChevronLeftIcon className="size-4" aria-hidden /> Previous
          </button>
        )}
        {navigation.next ? (
          <Link
            className={buttonClass}
            to={`/documents/${navigation.next.id}?${params}`}
            aria-label={`Next document: ${navigation.next.original_filename}`}
            title={navigation.next.original_filename}
          >
            Next document <ChevronRightIcon className="size-4" aria-hidden />
          </Link>
        ) : (
          <button type="button" className={buttonClass} disabled aria-label="Next document">
            Next document <ChevronRightIcon className="size-4" aria-hidden />
          </button>
        )}
      </div>
    </nav>
  );
}
