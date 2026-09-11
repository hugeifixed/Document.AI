import { ArrowPathIcon, ExclamationTriangleIcon, HomeIcon } from "@heroicons/react/24/outline";
import { useEffect, useRef } from "react";
import { isRouteErrorResponse, Link, useRouteError } from "react-router-dom";

export function RouteError() {
  const error = useRouteError();
  const message = isRouteErrorResponse(error)
    ? error.statusText || `The server returned status ${error.status}.`
    : error instanceof Error
      ? error.message
      : "This page could not be displayed.";
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);

  return (
    <section
      className="grid min-h-[min(32rem,calc(100vh-9rem))] place-items-center py-8"
      aria-labelledby="route-error-title"
    >
      <div className="card card-border w-full max-w-xl border-base-300 bg-base-100">
        <div className="card-body items-center gap-5 p-6 text-center sm:p-10">
          <div className="grid size-14 place-items-center rounded-box bg-error/10 text-error" aria-hidden="true">
            <ExclamationTriangleIcon className="size-7" />
          </div>
          <div className="space-y-2">
            <p className="text-caption font-semibold uppercase tracking-wide text-secondary">Page error</p>
            <h1 id="route-error-title" ref={heading} tabIndex={-1} className="focus:outline-none">
              Something went wrong
            </h1>
            <p className="reading-copy text-secondary">{message}</p>
          </div>
          <div className="card-actions w-full flex-col-reverse justify-center gap-3 sm:flex-row">
            <Link to="/" className="btn btn-outline">
              <HomeIcon className="size-5" aria-hidden="true" /> Dashboard
            </Link>
            <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
              <ArrowPathIcon className="size-5" aria-hidden="true" /> Reload page
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
