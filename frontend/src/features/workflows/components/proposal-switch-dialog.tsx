import { useEffect, useId, useRef } from "react";

type Props = {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title?: string;
  description?: string;
  confirmLabel?: string;
};

export function ProposalSwitchDialog({
  open, onClose, onConfirm,
  title = "Discard proposal edits?",
  description = "Your unsaved changes will be lost. The current proposal remains available to resume.",
  confirmLabel = "Switch proposal",
}: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);
  return (
    <dialog ref={dialog} className="modal" aria-labelledby={titleId} onClose={onClose}>
      <div className="modal-box rounded-box">
        <h2 id={titleId} className="text-section-title">{title}</h2>
        <p className="my-3 text-sm text-secondary text-pretty">
          {description}
        </p>
        <div className="modal-action flex-wrap">
          <button type="button" className="btn btn-outline" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </dialog>
  );
}
