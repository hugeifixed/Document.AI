import { ArrowLeftIcon, HomeIcon, MapIcon } from "@heroicons/react/24/outline";
import { useEffect, useRef } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

export function NotFound() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = "Page not found · DocAI";
    heading.current?.focus();
    return () => { document.title = previousTitle; };
  }, [pathname]);

  function goBack() {
    navigate(-1);
  }

  return (
    <section className="grid min-h-[min(36rem,calc(100vh-9rem))] place-items-center py-8" aria-labelledby="not-found-title">
      <div className="card card-border w-full max-w-xl border-base-300 bg-base-100">
        <div className="card-body items-center gap-5 p-6 text-center sm:p-10">
          <div className="grid size-14 place-items-center rounded-box border border-accent bg-base-200 text-primary" aria-hidden="true">
            <MapIcon className="size-7" />
          </div>
          <div className="space-y-2">
            <p className="text-caption font-semibold uppercase tracking-wide text-secondary">Error 404</p>
            <h1 id="not-found-title" ref={heading} tabIndex={-1} className="focus:outline-none">Page not found</h1>
            <p className="reading-copy text-secondary">
              We couldn’t find <code className="rounded bg-base-200 px-1.5 py-0.5 font-mono text-sm text-base-content [overflow-wrap:anywhere]">{pathname}</code>.
              Check the address or return to a page you know.
            </p>
          </div>
          <div className="flex w-full flex-col-reverse justify-center gap-3 sm:flex-row">
            <button type="button" className="btn btn-outline" onClick={goBack}>
              <ArrowLeftIcon className="size-5" aria-hidden="true" />Go back
            </button>
            <Link to="/" className="btn btn-primary">
              <HomeIcon className="size-5" aria-hidden="true" />Dashboard
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
