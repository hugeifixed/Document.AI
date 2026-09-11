/** Native <dialog> (never the checkbox variant): focus trapped by the platform, Esc closes, focus returns to the invoker. */
import { useEffect, useId, useRef, useState } from "react";
import { AsyncButton, Field } from "./ui";

export function ConfirmDialog({ open, title, summary, confirmLabel, typed, reasonLabel, reasonHelp, reasonRequired = false, destructive, pending = false, onConfirm, onClose }:
  { open: boolean; title: string; summary: React.ReactNode; confirmLabel: string; typed?: string; reasonLabel?: string; reasonHelp?: string; reasonRequired?: boolean; destructive?: boolean; pending?: boolean; onConfirm: (reason: string) => void | Promise<void>; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  useEffect(() => { const d = ref.current; if (!d) return; if (open && !d.open) { setText(""); setReason(""); d.showModal(); } if (!open && d.open) d.close(); }, [open]);
  const ok = (!typed || text === typed) && (!reasonRequired || reason.trim().length > 0);
  const close = () => { if (!pending) onClose(); };
  return (
    <dialog ref={ref} className="modal" onCancel={(event) => { if (pending) event.preventDefault(); }} onClose={close} aria-labelledby={`${id}-title`}>
      <div className="modal-box rounded-box">
        <h2 id={`${id}-title`}>{title}</h2>
        <div className="my-3 text-sm">{summary}</div>
        {typed && (<Field id={`${id}-confirmation`} label={<>Type <span className="font-mono">{typed}</span> to confirm</>} className="mb-4">
          <input id={`${id}-confirmation`} className="input border-(--border-interactive) w-full" value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" /></Field>)}
        {reasonLabel && <Field id={`${id}-reason`} label={reasonLabel} required={reasonRequired} className="mb-4">
          <textarea id={`${id}-reason`} className="textarea min-h-24 w-full border-(--border-interactive)" value={reason} onChange={(event) => setReason(event.target.value)} required={reasonRequired} aria-describedby={reasonHelp ? `${id}-reason-help` : undefined} />
          {reasonHelp && <p id={`${id}-reason-help`} className="field-help text-sm text-secondary">{reasonHelp}</p>}
        </Field>}
        <form method="dialog" className="modal-action flex-wrap">
          <button className="btn btn-outline" disabled={pending}>Cancel</button>
          <AsyncButton className={`btn ${destructive ? "btn-error" : "btn-primary"}`} pending={pending} pendingLabel="Applying…" disabled={!ok} onClick={(event) => { event.preventDefault(); void onConfirm(reason.trim()); }}>{confirmLabel}</AsyncButton>
        </form>
      </div>
    </dialog>
  );
}
