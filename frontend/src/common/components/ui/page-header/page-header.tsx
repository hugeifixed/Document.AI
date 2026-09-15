import type { ReactNode } from "react";
export function PageHeader({ title, action, children }: { title: string; action?: ReactNode; children?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1>{title}</h1>
        {children &&
          (typeof children === "string" ? (
            <p className="reading-copy mt-2 text-secondary">{children}</p>
          ) : (
            <div className="mt-2 flex flex-wrap gap-2 text-sm text-secondary [overflow-wrap:anywhere]">{children}</div>
          ))}
      </div>
      {action && <div className="min-w-0 max-w-full">{action}</div>}
    </header>
  );
}
