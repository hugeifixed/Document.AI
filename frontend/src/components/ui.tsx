/** Small shared components implementing DESIGN.md semantics. */
import {
  CheckIcon,
  ChevronDownIcon,
  ExclamationTriangleIcon,
  MinusIcon,
  PencilIcon,
  XMarkIcon,
} from "@heroicons/react/20/solid";
import {
  type ButtonHTMLAttributes,
  type ComponentPropsWithRef,
  forwardRef,
  type ReactNode,
  type SelectHTMLAttributes,
  useEffect,
} from "react";
import { Link } from "react-router-dom";
import { announce } from "@/a11y/announce";

/** Reserve both labels so pending feedback never moves nearby controls. */
export function AsyncButton({
  pending,
  pendingLabel,
  children,
  disabled,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { pending: boolean; pendingLabel: string; children: ReactNode }) {
  useEffect(() => {
    if (pending) return announce(pendingLabel);
  }, [pending, pendingLabel]);
  return (
    <button {...props} type={type} disabled={disabled || pending} aria-busy={pending}>
      <span className="grid min-w-0">
        <span className={`col-start-1 row-start-1 ${pending ? "invisible" : ""}`} aria-hidden={pending}>
          {children}
        </span>
        <span
          className={`col-start-1 row-start-1 inline-flex items-center justify-center gap-2 ${pending ? "" : "invisible"}`}
          aria-hidden={!pending}
        >
          <span className="inline-flex size-4 items-center justify-center" aria-hidden="true">
            {pending && <span className="loading loading-spinner loading-xs" />}
          </span>
          {pendingLabel}
        </span>
      </span>
    </button>
  );
}

/** Decorative loading shape; its container supplies one readable status message. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <span aria-hidden="true" className={`skeleton block ${className}`} />;
}

/** Native select with a dedicated caret area so long labels cannot paint under the icon. */
export const SelectControl = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function SelectControl({ className = "", children, ...props }, ref) {
    return (
      <span className="relative block min-w-0 max-w-full">
        <select ref={ref} className={`select select-managed-caret peer w-full ${className}`} {...props}>
          {children}
        </select>
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-px end-px z-10 grid w-10 place-items-center rounded-e-[calc(var(--radius-field)-1px)] bg-base-100 text-base-content peer-disabled:bg-base-200 peer-disabled:text-base-content/40"
        >
          <ChevronDownIcon className="size-4" />
        </span>
      </span>
    );
  },
);

/** §6.1 Extraction confidence — three cues minimum: color + glyph + text; numeric value always shown. */
export function ConfidenceCue({
  score,
  status,
  thresholds = { high: 0.95, medium: 0.8 },
  label,
}: {
  score: number | null | undefined;
  status?: string;
  thresholds?: { high: number; medium: number };
  label?: string;
}) {
  if (status === "corrected")
    return (
      <span
        className="inline-flex items-center gap-1 text-info text-sm"
        aria-label={`${label ?? ""} edited by reviewer`}
      >
        <PencilIcon className="size-3.5" aria-hidden /> Edited
      </span>
    );
  if (score == null)
    return (
      <span className="inline-flex items-center gap-1 text-sm text-secondary" aria-label={`${label ?? ""} not found`}>
        <MinusIcon className="size-3.5" aria-hidden /> Not found
      </span>
    );
  const pct = Math.round(score * 100);
  if (score >= thresholds.high)
    return (
      <span
        className="inline-flex items-center gap-1 text-success text-sm tabular-nums"
        title="Model confidence is independent of source verification."
        aria-label={`${label ?? ""} model confidence ${pct} percent, high`}
      >
        <span aria-hidden className="inline-block size-2.5 rounded-full bg-success" />
        {pct}% High
      </span>
    );
  if (score >= thresholds.medium)
    return (
      <span
        className="inline-flex items-center gap-1 text-sm tabular-nums text-secondary"
        title="Model confidence is independent of source verification."
        aria-label={`${label ?? ""} model confidence ${pct} percent, medium`}
      >
        <span
          aria-hidden
          className="inline-block size-2.5 rounded-full border-2 border-current"
          style={{ background: "linear-gradient(90deg, currentColor 50%, transparent 50%)" }}
        />
        {pct}% Medium
      </span>
    );
  return (
    <span
      className="inline-flex items-center gap-1 text-warning text-sm tabular-nums"
      title="Model confidence is independent of source verification."
      aria-label={`${label ?? ""} model confidence ${pct} percent, needs review`}
    >
      <ExclamationTriangleIcon className="size-3.5" aria-hidden />
      {pct}% Needs review
    </span>
  );
}

const CHIP: Record<string, { cls: string; glyph: ReactNode; text: string }> = {
  queued: {
    cls: "badge-ghost",
    glyph: <span aria-hidden className="inline-block size-2 rounded-full border border-current" />,
    text: "Queued",
  },
  running: {
    cls: "badge-soft badge-info",
    glyph: <span aria-hidden className="inline-block size-2 rounded-full bg-current" />,
    text: "Processing",
  },
  processing: {
    cls: "badge-soft badge-info",
    glyph: <span aria-hidden className="inline-block size-2 rounded-full bg-current" />,
    text: "Processing",
  },
  in_progress: {
    cls: "badge-soft badge-info",
    glyph: <span aria-hidden className="inline-block size-2 rounded-full bg-current" />,
    text: "In progress",
  },
  not_started: { cls: "badge-ghost", glyph: <MinusIcon className="size-3" aria-hidden />, text: "Not started" },
  needs_review: {
    cls: "badge-soft badge-warning",
    glyph: <ExclamationTriangleIcon className="size-3" aria-hidden />,
    text: "Needs review",
  },
  pending: {
    cls: "badge-ghost",
    glyph: <span aria-hidden className="inline-block size-2 rounded-full border border-current" />,
    text: "Pending",
  },
  auto_accepted: {
    cls: "badge-soft badge-success",
    glyph: <CheckIcon className="size-3" aria-hidden />,
    text: "Auto-accepted",
  },
  accepted: { cls: "badge-soft badge-success", glyph: <CheckIcon className="size-3" aria-hidden />, text: "Verified" },
  corrected: { cls: "badge-soft badge-info", glyph: <PencilIcon className="size-3" aria-hidden />, text: "Corrected" },
  rejected: { cls: "badge-soft badge-error", glyph: <XMarkIcon className="size-3" aria-hidden />, text: "Rejected" },
  absent: { cls: "badge-ghost", glyph: <MinusIcon className="size-3" aria-hidden />, text: "Marked absent" },
  succeeded: {
    cls: "badge-soft badge-success",
    glyph: <CheckIcon className="size-3" aria-hidden />,
    text: "Succeeded",
  },
  partial: {
    cls: "badge-soft badge-warning",
    glyph: <ExclamationTriangleIcon className="size-3" aria-hidden />,
    text: "Partial",
  },
  failed: { cls: "badge-soft badge-error", glyph: <XMarkIcon className="size-3" aria-hidden />, text: "Failed" },
  cancelled: { cls: "badge-ghost", glyph: <XMarkIcon className="size-3" aria-hidden />, text: "Cancelled" },
  validated: {
    cls: "badge-soft badge-success",
    glyph: <CheckIcon className="size-3" aria-hidden />,
    text: "Validated",
  },
  processed: {
    cls: "badge-soft badge-success",
    glyph: <CheckIcon className="size-3" aria-hidden />,
    text: "Processed",
  },
  uploaded: {
    cls: "badge-ghost",
    glyph: <span aria-hidden className="inline-block size-2 rounded-full border border-current" />,
    text: "Uploaded",
  },
  draft: { cls: "badge-ghost", glyph: <PencilIcon className="size-3" aria-hidden />, text: "Draft" },
  approved: { cls: "badge-soft badge-success", glyph: <CheckIcon className="size-3" aria-hidden />, text: "Approved" },
  retired: { cls: "badge-ghost", glyph: <MinusIcon className="size-3" aria-hidden />, text: "Retired" },
  passed: { cls: "badge-soft badge-success", glyph: <CheckIcon className="size-3" aria-hidden />, text: "Passed" },
  warning: {
    cls: "badge-soft badge-warning",
    glyph: <ExclamationTriangleIcon className="size-3" aria-hidden />,
    text: "Warning",
  },
  not_run: { cls: "badge-ghost", glyph: <MinusIcon className="size-3" aria-hidden />, text: "Not run" },
};
/** §6.2 status chip: every chip carries a text label; the glyph is redundancy. */
export function StatusChip({ status }: { status: string }) {
  const c = CHIP[status] || { cls: "badge-ghost", glyph: null, text: status };
  return (
    <span className={`badge badge-sm gap-1 whitespace-nowrap ${c.cls}`}>
      {c.glyph}
      {c.text}
    </span>
  );
}

/** Brand mark (DESIGN.md §3.4): three rings cropped at the top-right of the navy tile, the orange bar bottom-left; same drawing as public/favicon.svg. Decorative; pair with a visible or accessible name. */
export function BrandMark({ size = 28, className = "" }: { size?: number; className?: string }) {
  const glyph = Math.round(size * 0.57);
  return (
    <span
      aria-hidden="true"
      className={`relative inline-grid shrink-0 place-items-center overflow-hidden bg-(--brand-mark-tile) text-white shadow-[0_0_0_1px_var(--brand-mark-ring)] ${className}`}
      style={{ width: size, height: size, borderRadius: Math.round(size * 0.28) }}
    >
      <svg
        className="absolute inset-0"
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.1"
      >
        <circle cx="19" cy="5" r="13" opacity="0.5" />
        <circle cx="19" cy="5" r="9" opacity="0.7" />
        <circle cx="19" cy="5" r="5" />
      </svg>
      <svg className="relative" width={glyph} height={glyph} viewBox="0 0 24 24" fill="none">
        <rect x="3" y="15.5" width="9" height="3" rx="1.5" fill="var(--color-accent)" />
      </svg>
    </span>
  );
}

/** Form group (§11): label above the control; help and error text keep the §15 rhythm through the `field` utility. */
export function Field({
  id,
  label,
  labelAction,
  required,
  className = "",
  children,
}: {
  id?: string;
  label: ReactNode;
  labelAction?: ReactNode;
  required?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const fieldLabel = (
    <label className="label" htmlFor={id}>
      {label}
      {required && <span aria-hidden> *</span>}
    </label>
  );
  return (
    <div className={`field ${className}`}>
      {labelAction ? (
        <div className="field-label-row flex items-center gap-2">
          {fieldLabel}
          {labelAction}
        </div>
      ) : (
        fieldLabel
      )}
      {children}
    </div>
  );
}

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

export function Breadcrumbs({ items }: { items: { label: string; to?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-3 text-sm text-secondary">
      <ol className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {items.map((item, index) => (
          <li key={`${item.label}-${index}`} className="flex min-w-0 items-center gap-2">
            {index > 0 && <span aria-hidden="true">/</span>}
            {item.to ? (
              <Link className="link link-hover" to={item.to}>
                {item.label}
              </Link>
            ) : (
              <span className="min-w-0 [overflow-wrap:anywhere]" aria-current="page">
                {item.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function ContextChip({ children }: { children: ReactNode }) {
  return <span className="badge badge-outline badge-sm">{children}</span>;
}

export function EmptyState({ text, action }: { text: string; action?: ReactNode }) {
  return (
    <div className="rounded-box border border-dashed border-base-300 p-8 text-center text-secondary">
      <p className="mb-3">{text}</p>
      {action}
    </div>
  );
}

/** Overflowing data must remain scrollable with a keyboard, including in Safari. */
export function ScrollRegion({
  label,
  children,
  className = "",
  ...props
}: ComponentPropsWithRef<"section"> & { label: string }) {
  return (
    // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Focus enables arrow-key scrolling of this named region.
    <section {...props} aria-label={label} tabIndex={0} className={`min-w-0 overflow-auto ${className}`}>
      {children}
    </section>
  );
}

export function TableSearch({
  id,
  value,
  onChange,
  placeholder,
  className = "",
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  className?: string;
}) {
  return (
    <Field id={id} label="Search" className={className}>
      <input
        id={id}
        type="search"
        className="input input-sm w-full border-(--border-interactive)"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
    </Field>
  );
}

/** Surface (§10.1). `flush` pulls a table out to the card edges so its cell text aligns with the title (§15). */
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

export function Stat({ label, value, hint, to }: { label: string; value: ReactNode; hint?: string; to?: string }) {
  const content = (
    <div className="stat min-w-0 content-start gap-1 p-4 [overflow-wrap:anywhere] sm:px-5">
      <div className="stat-title whitespace-normal text-sm font-medium text-secondary">{label}</div>
      <div className="stat-value whitespace-normal text-[1.625rem] font-semibold leading-tight tracking-tight lining-nums tabular-nums">
        {value}
      </div>
      {hint && <div className="stat-desc whitespace-normal text-caption tabular-nums text-(--color-ink-3)">{hint}</div>}
    </div>
  );
  const className =
    "stats elevation-raised min-w-0 rounded-box border border-base-300 bg-base-100 motion-safe:transition-[border-color,box-shadow]";
  return to ? (
    <Link
      to={to}
      className={`${className} hover:border-primary`}
      aria-label={`${label}: ${String(value)}${hint ? `. ${hint}` : ""}`}
    >
      {content}
    </Link>
  ) : (
    <div className={className}>{content}</div>
  );
}

export function fmtPct(v: number | null | undefined, d = 1) {
  return v == null ? "—" : `${(v * 100).toFixed(d)}%`;
}
export function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  return (
    <time className="whitespace-nowrap lining-nums tabular-nums" dateTime={iso} title={iso}>
      {d.toLocaleString()}
    </time>
  );
}
export function fmtBytes(n: number) {
  return n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`;
}
