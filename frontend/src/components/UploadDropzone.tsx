/** Accessible upload queue with bounded concurrency and per-file recovery.
 * Drag-and-drop is optional: the native file input remains the primary path. */
import {
  ArrowPathIcon,
  CheckCircleIcon,
  CloudArrowUpIcon,
  DocumentIcon,
  ExclamationTriangleIcon,
  XMarkIcon,
} from "@heroicons/react/20/solid";
import { memo, useEffect, useMemo, useState } from "react";
import { useDropzone } from "react-dropzone";
import { type UploadItem, type UploadStatus, type UploadSummary, useUploadQueue } from "@/hooks/useUploadQueue";

const ACCEPT = {
  "application/pdf": [".pdf"],
  "image/jpeg": [".jpg", ".jpeg"],
  "image/png": [".png"],
  "image/tiff": [".tif", ".tiff"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
  "application/vnd.ms-excel": [".xls"],
  "text/plain": [".txt"],
};
const QUEUE_PAGE_SIZE = 50;

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && value >= 1024; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${unit}`;
}

function statusLabel(item: UploadItem) {
  if (item.status === "uploading" && item.progress >= 100) return "Validating and storing";
  const labels: Record<UploadStatus, string> = {
    queued: "Ready",
    uploading: "Uploading",
    accepted: "Accepted",
    rejected: "Rejected",
    failed: "Upload failed",
    cancelled: "Cancelled",
  };
  return labels[item.status];
}

const UploadQueueRow = memo(function UploadQueueRow({
  item,
  uploading,
  onRemove,
}: {
  item: UploadItem;
  uploading: boolean;
  onRemove: (id: string) => void;
}) {
  return (
    <li className="flex gap-3 p-3">
      {item.status === "accepted" ? (
        <CheckCircleIcon className="mt-0.5 size-5 shrink-0 text-success" aria-hidden="true" />
      ) : item.status === "rejected" || item.status === "failed" ? (
        <ExclamationTriangleIcon className="mt-0.5 size-5 shrink-0 text-error" aria-hidden="true" />
      ) : (
        <DocumentIcon className="mt-0.5 size-5 shrink-0 text-secondary" aria-hidden="true" />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
          <p className="truncate text-sm font-medium" title={item.file.name}>
            {item.file.name}
          </p>
          <span className="text-xs text-secondary">
            {formatBytes(item.file.size)} · {statusLabel(item)}
          </span>
        </div>
        {item.status === "uploading" && (
          <progress
            className="progress progress-primary mt-2 h-1.5 w-full"
            value={item.progress}
            max={100}
            aria-label={`${item.file.name} upload progress`}
          />
        )}
        {item.message && (
          <p className="mt-1 text-sm text-base-content">
            {item.message}{" "}
            {item.errorCode && <span className="font-mono text-xs text-secondary">{item.errorCode}</span>}
          </p>
        )}
      </div>
      {!uploading && ["queued", "failed", "cancelled"].includes(item.status) && (
        <button
          type="button"
          className="btn btn-square btn-ghost btn-xs shrink-0"
          aria-label={`Remove ${item.file.name} from upload queue`}
          onClick={() => onRemove(item.id)}
        >
          <XMarkIcon className="size-4" aria-hidden="true" />
        </button>
      )}
    </li>
  );
});

export function UploadDropzone({
  datasetId,
  onDone,
  maxMb = 100,
  maxFiles = 500,
}: {
  datasetId: string;
  onDone: (summary: UploadSummary) => void;
  maxMb?: number;
  maxFiles?: number;
}) {
  const [queuePage, setQueuePage] = useState(1);
  const { items, uploading, addFiles, removeItem, clearCompleted, startUploads, cancelUploads } = useUploadQueue({
    datasetId,
    onDone,
    maxFiles,
  });
  useEffect(() => setQueuePage(1), [datasetId]);

  const { getRootProps, getInputProps, isDragActive, isDragAccept, isDragReject } = useDropzone({
    onDrop: addFiles,
    accept: ACCEPT,
    maxFiles,
    maxSize: maxMb * 1_048_576,
    disabled: uploading,
    noClick: true,
    noKeyboard: true,
  });

  const readyCount = items.filter((item) => ["queued", "failed", "cancelled"].includes(item.status)).length;
  const retrying =
    readyCount > 0 &&
    items
      .filter((item) => ["queued", "failed", "cancelled"].includes(item.status))
      .every((item) => item.status !== "queued");
  const completedCount = items.filter((item) => item.status === "accepted" || item.status === "rejected").length;
  const totalBytes = useMemo(() => items.reduce((total, item) => total + item.file.size, 0), [items]);
  const totalQueuePages = Math.max(1, Math.ceil(items.length / QUEUE_PAGE_SIZE));
  const currentQueuePage = Math.min(queuePage, totalQueuePages);
  const visibleItems = useMemo(
    () => items.slice((currentQueuePage - 1) * QUEUE_PAGE_SIZE, currentQueuePage * QUEUE_PAGE_SIZE),
    [currentQueuePage, items],
  );
  useEffect(() => {
    if (queuePage > totalQueuePages) setQueuePage(totalQueuePages);
  }, [queuePage, totalQueuePages]);
  const dropState = isDragReject
    ? "border-error bg-error/10"
    : isDragAccept
      ? "border-success bg-success/10"
      : isDragActive
        ? "border-primary bg-primary/10"
        : "border-(--border-interactive)";

  return (
    <div aria-busy={uploading}>
      <div className="mb-3 rounded-box bg-base-200 p-3 text-sm text-secondary">
        <p>
          Files wait in a reviewable queue, then upload two at a time. Each file can finish or retry independently.
          Workflow processing and Azure layout analysis begin later when you start a run.
        </p>
        <p className="mt-1">
          PDF, JPEG, PNG, TIFF, DOCX, XLSX, XLS, or TXT · {maxMb} MB per file · up to {maxFiles} files
        </p>
      </div>
      <div
        {...getRootProps({
          className: `rounded-box border-2 border-dashed p-4 text-center transition-colors motion-reduce:transition-none sm:p-6 ${dropState} ${uploading ? "cursor-not-allowed opacity-60" : ""}`,
        })}
      >
        <CloudArrowUpIcon className="mx-auto size-8 text-secondary" aria-hidden="true" />
        <label className="fieldset mx-auto mt-2 max-w-md gap-2 p-0 text-sm">
          <span className="label justify-center font-medium text-base-content">Choose documents</span>
          <input
            {...getInputProps({ style: {}, tabIndex: 0 })}
            className="file-input w-full min-w-0 border-(--border-interactive)"
          />
        </label>
        <p className="mt-2 text-sm text-secondary">or drag and drop them here</p>
      </div>

      {items.length > 0 && (
        <div className="mt-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium">
              {items.length} file{items.length === 1 ? "" : "s"} · {formatBytes(totalBytes)}
            </p>
            <div className="flex flex-wrap gap-2">
              {completedCount > 0 && !uploading && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={clearCompleted}>
                  Clear completed
                </button>
              )}
              {uploading ? (
                <button type="button" className="btn btn-outline btn-sm" onClick={cancelUploads}>
                  <XMarkIcon className="size-4" aria-hidden="true" /> Cancel uploads
                </button>
              ) : (
                <button type="button" className="btn btn-primary btn-sm" disabled={!readyCount} onClick={startUploads}>
                  {retrying ? (
                    <ArrowPathIcon className="size-4" aria-hidden="true" />
                  ) : (
                    <CloudArrowUpIcon className="size-4" aria-hidden="true" />
                  )}
                  {readyCount
                    ? `${retrying ? "Retry" : "Upload"} ${readyCount} file${readyCount === 1 ? "" : "s"}`
                    : "Upload files"}
                </button>
              )}
            </div>
          </div>

          <ul
            className="mt-3 max-h-80 divide-y divide-base-300 overflow-y-auto rounded-box border border-base-300"
            aria-label="Upload queue"
          >
            {visibleItems.map((item) => (
              <UploadQueueRow key={item.id} item={item} uploading={uploading} onRemove={removeItem} />
            ))}
          </ul>
          {totalQueuePages > 1 && (
            <nav
              className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm"
              aria-label="Upload queue pages"
            >
              <span className="text-secondary">
                Showing {(currentQueuePage - 1) * QUEUE_PAGE_SIZE + 1}–
                {Math.min(currentQueuePage * QUEUE_PAGE_SIZE, items.length)} of {items.length}
              </span>
              <div className="join">
                <button
                  type="button"
                  className="btn btn-sm join-item"
                  disabled={currentQueuePage === 1}
                  onClick={() => setQueuePage((page) => Math.max(1, page - 1))}
                >
                  Previous
                </button>
                <span className="btn btn-sm join-item pointer-events-none" aria-current="page">
                  Page {currentQueuePage} of {totalQueuePages}
                </span>
                <button
                  type="button"
                  className="btn btn-sm join-item"
                  disabled={currentQueuePage === totalQueuePages}
                  onClick={() => setQueuePage((page) => Math.min(totalQueuePages, page + 1))}
                >
                  Next
                </button>
              </div>
            </nav>
          )}
        </div>
      )}
    </div>
  );
}
