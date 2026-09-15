import { Field } from "@/common/components/ui/field/field";
import { useEffect, useId, useRef, useState } from "react";
import { AsyncButton, } from "./ui";

interface ReclassificationDialogProps {
  documentName: string;
  initialCategory: string;
  suggestions: string[];
  pending: boolean;
  onConfirm: (category: string, reason: string) => void;
  onClose: () => void;
}

/** Accessible category editor. Native dialog provides focus trapping, Escape, and focus restoration. */
export function ReclassificationDialog({
  documentName,
  initialCategory,
  suggestions,
  pending,
  onConfirm,
  onClose,
}: ReclassificationDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const categoryRef = useRef<HTMLInputElement>(null);
  const id = useId();
  const [category, setCategory] = useState(initialCategory);
  const [reason, setReason] = useState("");
  const normalizedCategory = category.trim();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || dialog.open) return;
    dialog.showModal();
    categoryRef.current?.focus();
    categoryRef.current?.select();
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
            if (normalizedCategory && normalizedCategory !== initialCategory) {
              onConfirm(normalizedCategory, reason.trim());
            }
          }}
        >
          <h2 id={`${id}-title`}>Correct document classification</h2>
          <p id={`${id}-description`} className="mt-2 text-sm text-secondary">
            Choose the category that best describes this document. The original prediction remains in the audit history.
          </p>

          <div className="mt-4 rounded-box bg-base-200 px-3 py-2">
            <p className="text-caption font-medium text-secondary">Document</p>
            <p className="mt-1 [overflow-wrap:anywhere]">{documentName}</p>
          </div>

          <Field id={`${id}-category`} label="Correct category" required className="mt-4">
            <input
              ref={categoryRef}
              id={`${id}-category`}
              type="text"
              className="input w-full border-(--border-interactive)"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              list={`${id}-category-options`}
              maxLength={64}
              autoComplete="off"
              required
            />
            <datalist id={`${id}-category-options`}>
              {suggestions.map((suggestion) => (
                <option key={suggestion} value={suggestion}>
                  {suggestion}
                </option>
              ))}
            </datalist>
            <p className="field-help text-sm text-secondary">Use a configured category key.</p>
          </Field>

          <Field id={`${id}-reason`} label="Review note (optional)" className="mt-4">
            <textarea
              id={`${id}-reason`}
              className="textarea min-h-20 w-full border-(--border-interactive)"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </Field>

          <div className="modal-action flex-wrap">
            <button
              type="button"
              className="btn btn-outline"
              disabled={pending}
              onClick={() => dialogRef.current?.close()}
            >
              Cancel
            </button>
            <AsyncButton
              type="submit"
              className="btn btn-primary"
              pending={pending}
              pendingLabel="Saving…"
              disabled={!normalizedCategory || normalizedCategory === initialCategory}
            >
              Save classification
            </AsyncButton>
          </div>
        </form>
      </div>
      <form method="dialog" className="modal-backdrop">
        <button aria-label="Close classification dialog" disabled={pending}>
          Close
        </button>
      </form>
    </dialog>
  );
}
