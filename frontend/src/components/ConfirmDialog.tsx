/** Native <dialog> (never the checkbox variant): focus trapped by the platform, Esc closes, focus returns to the invoker. */
import { useEffect, useId, useRef, useState } from "react";
import { AsyncButton, Field } from "./ui";

export function ConfirmDialog({ open, title, summary, confirmLabel, typed, destructive, pending = false, onConfirm, onClose }:
  { open: boolean; title: string; summary: React.ReactNode; confirmLabel: string; typed?: string; destructive?: boolean; pending?: boolean; onConfirm: () => void | Promise<void>; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  const [text, setText] = useState("");
  useEffect(() => { const d = ref.current; if (!d) return; if (open && !d.open) { setText(""); d.showModal(); } if (!open && d.open) d.close(); }, [open]);
  const ok = !typed || text === typed;
  return (
    <dialog ref={ref} className="modal" onClose={onClose} aria-labelledby={`${id}-title`}>
      <div className="modal-box rounded-box">
        <h2 id={`${id}-title`}>{title}</h2>
        <div className="my-3 text-sm">{summary}</div>
        {typed && (<Field id={`${id}-confirmation`} label={<>Type <span className="font-mono">{typed}</span> to confirm</>} className="mb-4">
          <input id={`${id}-confirmation`} className="input border-(--border-interactive) w-full" value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" /></Field>)}
        <form method="dialog" className="modal-action flex-wrap">
          <button className="btn btn-outline">Cancel</button>
          <AsyncButton className={`btn ${destructive ? "btn-error" : "btn-primary"}`} pending={pending} pendingLabel="Applying…" disabled={!ok} onClick={() => void onConfirm()}>{confirmLabel}</AsyncButton>
        </form>
      </div>
    </dialog>
  );
}
