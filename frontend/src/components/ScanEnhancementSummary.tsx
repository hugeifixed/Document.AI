import { ExclamationTriangleIcon } from "@heroicons/react/20/solid";
import type { RunItem } from "@/api/types";

/** Processing outcomes stay beside the item status, with details disclosed on demand. */
export function ScanEnhancementSummary({ item }: { item: RunItem }) {
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
  return (
    <div className="mt-2 max-w-52 whitespace-normal [overflow-wrap:anywhere] text-caption">
      <p className="text-secondary">{counts || (quality.status === "applied" ? "Scans prepared" : "Original used")}</p>
      <details className="mt-2">
        <summary
          className={`min-h-10 cursor-pointer content-center rounded-field ${warnings.length ? "text-warning" : "text-primary"}`}
        >
          {warnings.length > 0 && <ExclamationTriangleIcon className="mr-1 inline size-4" aria-hidden="true" />}
          {warnings.length
            ? `Scan details · ${warnings.length} warning${warnings.length === 1 ? "" : "s"}`
            : "Scan details"}
        </summary>
        <dl className="grid gap-2 text-secondary">
          <div>
            <dt className="font-medium">Pages examined</dt>
            <dd className="tabular-nums">{(quality.pages_examined ?? 0).toLocaleString()}</dd>
          </div>
          <div>
            <dt className="font-medium">Enhancement profile</dt>
            <dd>{quality.profile}</dd>
          </div>
        </dl>
        {warnings.length > 0 && (
          <ul className="mt-2 grid gap-2 text-warning">
            {warnings.map((warning, index) => (
              <li key={`${warning.code}-${index}`}>
                <p>{warning.message}</p>
                {warning.pages.length > 0 && (
                  <p>
                    Page{warning.pages.length === 1 ? "" : "s"} {warning.pages.join(", ")}
                  </p>
                )}
                <p className="font-mono text-caption">{warning.code}</p>
              </li>
            ))}
          </ul>
        )}
      </details>
    </div>
  );
}
