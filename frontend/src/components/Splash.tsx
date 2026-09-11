import { ErrorNotice } from "@/components/ErrorNotice";
import { BrandMark } from "@/components/ui";

/** The three lines the boot screen cycles through (3.5s each). All are existing sign-in copy. */
const STATEMENTS = [
  "Every extracted field, grounded in the page it came from.",
  "Confidence scores, provenance, and an audit trail on every run.",
  "Reviewers spend time only where the model is unsure.",
];

const STATEMENT_CLASS = "splash-cycle [grid-area:1/1] text-[26px] font-semibold leading-[1.2] tracking-[-0.02em] text-balance sm:text-[30px] lg:text-[34px]";

/**
 * Boot screen (DESIGN.md §9.5): shown while the session is checked, and when that check fails.
 * Desktop: brand top-left, statement bottom-left. Below `lg`: both centered.
 * On error the notice sits top-right, inset by the page padding, and the sweep stops.
 */
export function Splash({ error = false, onRetry }: { error?: boolean; onRetry?: () => void }) {
  return (
    <main className="splash relative flex min-h-screen flex-col overflow-hidden p-5 text-(--splash-content) max-lg:items-center max-lg:justify-center max-lg:gap-9 max-lg:text-center sm:p-8 lg:justify-between lg:p-10">
      <svg aria-hidden="true" viewBox="0 0 380 380" className="splash-rings pointer-events-none absolute -top-[180px] -right-[220px] size-[520px] sm:-top-[260px] sm:-right-[320px] sm:size-[820px] lg:-top-[300px] lg:-right-[360px] lg:size-[1100px]">
        <circle cx="190" cy="190" r="170" fill="none" stroke="currentColor" />
        <circle cx="190" cy="190" r="120" fill="none" stroke="currentColor" />
        <circle cx="190" cy="190" r="70" fill="none" stroke="currentColor" />
      </svg>
      <div className="splash-rise relative flex items-center gap-3">
        <BrandMark size={40} />
        <h1 className="text-xl font-semibold tracking-tight">DocAI</h1>
      </div>
      <section aria-label="Account connection" className="splash-rise-2 relative flex w-full max-w-[560px] flex-col gap-7 max-lg:items-center">
        <div className="grid">
          {STATEMENTS.map((statement) => <p key={statement} className={STATEMENT_CLASS}>{statement}</p>)}
        </div>
        <div className="flex flex-col gap-3.5 max-lg:items-center">
          <output className="text-sm text-(--splash-muted)">{error ? "Not connected" : "Checking your session…"}</output>
          <div aria-hidden="true" className="relative h-[3px] w-[200px] overflow-hidden rounded-full bg-(--splash-track)">
            {!error && <div className="splash-sweep absolute inset-y-0 left-0 w-16 rounded-full bg-(--splash-sweep)" />}
          </div>
        </div>
      </section>
      {error && (
        <div className="splash-rise-2 absolute inset-x-5 top-5 rounded-(--radius-box) elevation-overlay sm:inset-x-auto sm:top-8 sm:right-8 sm:max-w-md lg:top-10 lg:right-10">
          <ErrorNotice message="We couldn’t connect to DocAI. Check your connection and try again." onRetry={onRetry} />
        </div>
      )}
    </main>
  );
}
