import type { ReactNode } from "react";
export function Card({
  title,
  action,
  children,
  className = "",
  flush = false,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  flush?: boolean;
}) {
  return (
    <section className={`card card-border elevation-raised min-w-0 border-base-300 bg-base-100 ${className}`}>
      <div className="card-body min-w-0 gap-0 p-4 sm:p-5">
        {(title || action) && (
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            {title && <h2 className="card-title text-base font-semibold leading-normal">{title}</h2>}
            {action}
          </div>
        )}
        {flush ? (
          <div className="-mx-4 -mb-4 min-w-0 overflow-hidden rounded-b-box sm:-mx-5 sm:-mb-5 [&_:is(th,td):first-child]:ps-4 [&_:is(th,td):last-child]:pe-4 sm:[&_:is(th,td):first-child]:ps-5 sm:[&_:is(th,td):last-child]:pe-5">
            {children}
          </div>
        ) : (
          children
        )}
      </div>
    </section>
  );
}
