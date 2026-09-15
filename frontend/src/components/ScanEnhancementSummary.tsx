import { ChevronRightIcon, ExclamationTriangleIcon } from "@heroicons/react/20/solid";
import { useId, useRef } from "react";
import { createPortal } from "react-dom";
import type { RunItem } from "@/common/types/api";

/** A compact table outcome; native dialog details never resize or get clipped by the table. */
export function ScanEnhancementSummary({ item }: { item: RunItem }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const id = useId();
  if (item.status === "running" && item.stage === "normalization")
    return <p className="mt-2 text-caption text-secondary">Preparing scans…</p>;
  const quality = item.input_quality;
  if (!quality?.status || quality.mode === "off" || quality.status === "off") return null;
  const warnings = quality.warnings ?? [];
  const adjusted = quality.pages_adjusted ?? 0;
  const skipped = quality.pages_skipped ?? 0;
  const counts = [
    adjusted > 0 ? `${adjusted.toLocaleString()} page${adjusted === 1 ? "" : "s"} adjusted` : null,
    skipped > 0 ? `${skipped.toLocaleString()} blank page${skipped === 1 ? "" : "s"} skipped` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const warningCount = `${warnings.length.toLocaleString()} warning${warnings.length === 1 ? "" : "s"}`;
  const laterFailure = item.status === "failed" && ["layout", "workflow"].includes(item.stage);
  return (
    <div className="mt-2 grid min-w-40 max-w-52 justify-items-start gap-1 whitespace-normal text-caption">
      <p className="text-secondary">{counts || (quality.status === "applied" ? "Scans prepared" : "Original used")}</p>
      {warnings.length > 0 && (
        <p className="flex items-center gap-2 text-warning">
          <ExclamationTriangleIcon className="size-5 shrink-0" aria-hidden="true" />
          {warningCount}
        </p>
      )}
      <button
        type="button"
        className="btn btn-ghost -ms-2 min-h-11 w-fit gap-1 px-2 text-caption font-medium text-primary sm:min-h-10"
        aria-label={`Scan details for ${item.document_name}${warnings.length ? `, ${warningCount}` : ""}`}
        aria-haspopup="dialog"
        aria-controls={id}
        onClick={() => {
          dialog.current?.showModal();
          heading.current?.focus();
        }}
      >
        <span>Scan details</span>
        <ChevronRightIcon className="size-4 shrink-0" aria-hidden="true" />
      </button>
      {createPortal(
        <dialog
          ref={dialog}
          id={id}
          className="modal p-4"
          aria-labelledby={`${id}-title`}
          aria-describedby={`${id}-file`}
        >
          <div className="modal-box max-h-[calc(100dvh-2rem)] w-full max-w-lg border border-base-300 p-4 sm:p-5">
            <h2 ref={heading} id={`${id}-title`} tabIndex={-1} className="text-section-title">
              Scan details
            </h2>
            <p id={`${id}-file`} className="mt-2 text-sm text-secondary [overflow-wrap:anywhere]">
              {item.document_name}
            </p>
            <p className="mt-4 text-sm">
              {quality.status === "fallback"
                ? "Original pages were retained where enhancement could not be completed."
                : quality.status === "bypassed"
                  ? "The original document was used without enhancement."
                  : "Scan preparation completed. The original document is unchanged."}
            </p>
            <dl className="mt-4 divide-y divide-base-300 text-sm">
              {[
                ["Pages examined", (quality.pages_examined ?? 0).toLocaleString()],
                ["Pages adjusted", adjusted.toLocaleString()],
                ["Blank pages skipped", skipped.toLocaleString()],
                ...(quality.duration_ms != null
                  ? [
                      [
                        "Preparation time",
                        `${(quality.duration_ms / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 })} s`,
                      ],
                    ]
                  : []),
                ...(quality.profile ? [["Enhancement profile", quality.profile]] : []),
              ].map(([label, value]) => (
                <div key={label} className="flex items-baseline justify-between gap-4 py-2">
                  <dt className="text-secondary">{label}</dt>
                  <dd
                    className={`shrink-0 tabular-nums ${label === "Enhancement profile" ? "font-mono text-caption" : "font-medium"}`}
                  >
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
            {skipped > 0 && (
              <p className="mt-2 text-caption text-secondary">
                Skipped blank pages remain in the document and are excluded from OCR.
              </p>
            )}
            {warnings.length > 0 && (
              <section className="mt-4" aria-labelledby={`${id}-warnings`}>
                <h3 id={`${id}-warnings`} className="text-sm font-medium">
                  Preparation warnings
                </h3>
                <ul className="mt-2 grid gap-2">
                  {warnings.map((warning, index) => (
                    <li key={`${warning.code}-${index}`} className="alert alert-soft alert-warning items-start text-sm">
                      <ExclamationTriangleIcon className="size-5 shrink-0" aria-hidden="true" />
                      <div className="min-w-0 [overflow-wrap:anywhere]">
                        <p>{warning.message}</p>
                        {warning.pages.length > 0 && (
                          <p className="mt-2 font-medium">
                            Page{warning.pages.length === 1 ? "" : "s"}{" "}
                            {warning.pages.map((page) => page.toLocaleString()).join(", ")}
                          </p>
                        )}
                        <p className="mt-2 font-mono text-caption">{warning.code}</p>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {laterFailure && (
              <section className="mt-4 border-t border-base-300 pt-4" aria-labelledby={`${id}-failure`}>
                <h3 id={`${id}-failure`} className="text-sm font-medium">
                  Processing stopped after scan preparation
                </h3>
                <p className="mt-2 text-sm text-secondary">
                  {item.stage === "workflow"
                    ? "Layout analysis finished, but the extraction workflow failed."
                    : "Layout analysis could not be completed."}
                </p>
                <p className="mt-2 text-sm text-error [overflow-wrap:anywhere]">{item.error_message}</p>
                <p className="mt-2 font-mono text-caption text-secondary">{item.error_code}</p>
              </section>
            )}
            <form method="dialog" className="modal-action">
              <button className="btn btn-outline">Close</button>
            </form>
          </div>
        </dialog>,
        document.body,
      )}
    </div>
  );
}
