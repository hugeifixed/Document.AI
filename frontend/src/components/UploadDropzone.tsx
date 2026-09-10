/** §10.1: drag-and-drop is never the only path — a real file input lives inside the drop zone;
 *  constraints are stated before the user acts; milestones (not ticks) are announced. */
import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { toast } from "sonner";
import { announce } from "@/a11y/announce";
import { http } from "@/api/client";
import type { Document } from "@/api/types";

const ACCEPT = { "application/pdf": [".pdf"], "image/jpeg": [".jpg", ".jpeg"], "image/png": [".png"], "image/tiff": [".tif", ".tiff"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"], "application/vnd.ms-excel": [".xls"], "text/plain": [".txt"] };

export function UploadDropzone({ datasetId, onDone, maxMb = 100, maxFiles = 500 }: { datasetId: string; onDone: () => void; maxMb?: number; maxFiles?: number }) {
  const [progress, setProgress] = useState<number | null>(null);
  const [result, setResult] = useState<{ accepted: Document[]; rejected: { filename: string; message: string; error_code: string }[] } | null>(null);
  const onDrop = useCallback(async (files: File[]) => {
    if (!files.length) return;
    const fd = new FormData(); files.forEach((f) => fd.append("files", f));
    setProgress(0); setResult(null); announce(`Uploading ${files.length} file(s)`);
    let half = false;
    try {
      const r = await http.post(`/datasets/${datasetId}/upload/`, fd, { headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (e) => { const p = e.total ? Math.round((e.loaded / e.total) * 100) : 0; setProgress(p); if (p >= 50 && !half) { half = true; announce("Upload 50% complete"); } } });
      const data = r.data.data; setResult(data); announce(`Upload complete: ${data.accepted.length} accepted, ${data.rejected.length} rejected`);
      toast.success(`${data.accepted.length} file(s) accepted`); onDone();
    } catch (e) {
      const err = e as { message?: string; status?: number; errors?: Record<string, unknown> } & { response?: { data?: { data?: { accepted: Document[]; rejected: { filename: string; message: string; error_code: string }[] } } } };
      if (err.status === 422 && (err as { errors?: Record<string, unknown> }).errors) { toast.error("Files were rejected. See details below."); }
      else toast.error(err.message || "Upload failed");
      announce("Upload failed", true);
    } finally { setProgress(null); }
  }, [datasetId, onDone]);
  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, accept: ACCEPT, maxFiles, maxSize: maxMb * 1048576, noClick: true, noKeyboard: true });
  return (
    <div>
      <p className="mb-2 text-sm text-secondary">Accepted: PDF, JPEG, PNG, TIFF, DOCX, XLSX, XLS, TXT. Max {maxMb} MB per file, {maxFiles} files per batch. Files are validated before storage.</p>
      <div {...getRootProps({ className: `rounded-box border-2 border-dashed border-(--border-interactive) p-4 text-center sm:p-6 ${isDragActive ? "bg-base-200" : ""}` })}>
        <label className="fieldset gap-2 p-0 text-sm"><span className="label justify-center text-base-content">Choose files</span><input {...getInputProps({ style: {}, tabIndex: 0 })} className="file-input w-full min-w-0 border-(--border-interactive)" /></label>
        <p className="mt-2 text-sm">or drop them here</p>
      </div>
      {progress !== null && <div className="mt-3"><progress className="progress progress-primary w-full" value={progress} max={100} aria-label="Upload progress" /><span className="text-sm tabular-nums">{progress}%</span></div>}
      {result && result.rejected.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm" aria-label="Rejected files">{result.rejected.map((r) => <li key={r.filename} className="rounded border-l-2 border-error pl-2"><strong>{r.filename}</strong>: {r.message} <span className="font-mono text-caption">{r.error_code}</span></li>)}</ul>
      )}
    </div>
  );
}
