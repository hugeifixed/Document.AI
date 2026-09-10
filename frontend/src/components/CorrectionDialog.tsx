import { useEffect, useId, useRef, useState } from "react";
import { AsyncButton } from "./ui";

interface CorrectionDialogProps {
  fieldName: string;
  initialValue: string;
  pending: boolean;
  onConfirm: (value: string) => void;
  onClose: () => void;
}

/** Accessible value editor for field review. Native dialog handles focus trapping, Escape, and focus restoration. */
export function CorrectionDialog({ fieldName, initialValue, pending, onConfirm, onClose }: CorrectionDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const valueRef = useRef<HTMLInputElement>(null);
  const id = useId();
  const [value, setValue] = useState(initialValue);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || dialog.open) return;
    dialog.showModal();
    valueRef.current?.focus();
    valueRef.current?.select();
  }, []);

  return (
    <dialog
      ref={dialogRef}
      className="modal"
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-description`}
      onCancel={(event) => {
        if (pending) event.preventDefault();
      }}
      onClose={onClose}
    >
      <div className="modal-box max-w-xl rounded-box">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onConfirm(value);
          }}
        >
          <h2 id={`${id}-title`}>Correct extracted value</h2>
          <p id={`${id}-description`} className="mt-2 text-sm text-secondary">
            Update the value that should be used for this field.
          </p>

          <div className="mt-4 rounded-box bg-base-200 px-3 py-2">
            <p className="text-caption font-medium text-secondary">Field</p>
            <p className="mt-1 [overflow-wrap:anywhere]">{fieldName}</p>
          </div>

          <fieldset className="fieldset mt-4 min-w-0 gap-2 p-0">
            <legend id={`${id}-value-label`} className="fieldset-legend">
              Corrected value
            </legend>
            <input
              ref={valueRef}
              type="text"
              className="input w-full border-(--border-interactive)"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              aria-labelledby={`${id}-value-label`}
              aria-describedby={`${id}-value-help`}
            />
            <p id={`${id}-value-help`} className="label whitespace-normal">
              The original extraction remains in the audit history.
            </p>
          </fieldset>

          <div className="modal-action flex-wrap">
            <button
              type="button"
              className="btn btn-outline"
              disabled={pending}
              onClick={() => dialogRef.current?.close()}
            >
              Cancel
            </button>
            <AsyncButton type="submit" className="btn btn-primary" pending={pending} pendingLabel="Saving…">
              Save correction
            </AsyncButton>
          </div>
        </form>
      </div>
      <form method="dialog" className="modal-backdrop">
        <button aria-label="Close correction dialog" disabled={pending}>
          Close
        </button>
      </form>
    </dialog>
  );
}
