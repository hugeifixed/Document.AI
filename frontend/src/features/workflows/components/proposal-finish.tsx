import { ChevronRightIcon } from "@heroicons/react/20/solid";

type Props = {
  busy: boolean;
  config: Record<string, unknown> | null;
  proposalHasEdits: boolean;
  refinement: string;
  onRefinementChange: (value: string) => void;
  onRefine: () => void;
  onUpdatePreview: () => void;
  onCopy: () => void;
  onUse: () => void;
};

export function ProposalFinish({
  busy,
  config,
  proposalHasEdits,
  refinement,
  onRefinementChange,
  onRefine,
  onUpdatePreview,
  onCopy,
  onUse,
}: Props) {
  return (
    <section
      className="rounded-box border border-base-300 bg-base-200 p-4 sm:p-5"
      aria-labelledby="playground-finish-heading"
    >
      <div>
        <h3 id="playground-finish-heading" className="font-semibold">
          Refine and finish
        </h3>
        <p className="mt-1 text-sm text-secondary text-pretty">
          Ask the assistant for a focused revision, or apply your field edits and continue with this proposal.
        </p>
      </div>
      <div className="mt-4 grid gap-4">
        <div className="rounded-box border border-base-300 bg-base-100 p-4">
          <label htmlFor="playground-refine" className="block text-sm font-medium">
            Refine the proposal
          </label>
          <input
            id="playground-refine"
            className="input border-(--border-interactive) mt-2 w-full"
            value={refinement}
            maxLength={1000}
            onChange={(event) => onRefinementChange(event.target.value)}
            placeholder="For example, add separate fields for boxes 12a through 12d"
          />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button type="button" className="btn btn-outline" disabled={busy || !refinement.trim()} onClick={onRefine}>
              Refine
            </button>
            <span className="text-caption text-secondary">This regenerates the proposal using the same examples.</span>
          </div>
        </div>
        {proposalHasEdits && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-box border border-warning bg-(--color-warning-soft) p-3">
            <p className="text-sm text-pretty">Your field edits are newer than the JSON preview.</p>
            <button type="button" className="btn btn-outline min-h-10" disabled={busy} onClick={onUpdatePreview}>
              Update JSON preview
            </button>
          </div>
        )}
        <details className="group/json min-w-0 rounded-box border border-base-300 bg-base-100 p-3">
          <summary className="flex min-h-10 cursor-pointer list-none items-center gap-2 font-medium [&::-webkit-details-marker]:hidden">
            <span className="grid size-7 shrink-0 place-items-center rounded-full bg-base-200 text-secondary">
              <ChevronRightIcon
                className="size-4 motion-safe:transition-transform motion-safe:duration-150 group-open/json:rotate-90"
                aria-hidden="true"
              />
            </span>
            Type-specific JSON preview
          </summary>
          <pre className="mt-3 max-h-72 overflow-auto border-t border-base-300 pt-3 whitespace-pre-wrap break-all text-xs">
            {JSON.stringify(config, null, 2)}
          </pre>
        </details>
        <div className="flex flex-wrap gap-3">
          <button type="button" className="btn btn-outline" disabled={busy} onClick={onCopy}>
            Copy JSON
          </button>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={onUse}>
            Use in builder
          </button>
        </div>
        <p className="text-caption text-secondary">
          Copy includes only type-specific JSON. Use in builder validates with the model and chunking controls above;
          Create version still saves the draft.
        </p>
      </div>
    </section>
  );
}
