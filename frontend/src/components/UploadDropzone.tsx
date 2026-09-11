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
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type FileRejection, useDropzone } from "react-dropzone";
import { toast } from "sonner";
import { announce } from "@/a11y/announce";
import { ApiError, http, isRequestCanceled } from "@/api/client";
import type { Document, Envelope, ErrorEnvelope } from "@/api/types";

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
const UPLOAD_CONCURRENCY = 2;
const QUEUE_PAGE_SIZE = 50;

type UploadStatus = "queued" | "uploading" | "accepted" | "rejected" | "failed" | "cancelled";
type UploadRejection = { filename: string; message: string; error_code: string; errors?: Record<string, unknown> };
type UploadResult = { accepted: Document[]; rejected: UploadRejection[] };
type UploadItem = {
  id: string;
  file: File;
  status: UploadStatus;
  progress: number;
  message?: string;
  errorCode?: string;
  document?: Document;
};

let uploadSequence = 0;

function itemId(file: File) {
  uploadSequence += 1;
  return `${file.name}-${file.size}-${file.lastModified}-${uploadSequence}`;
}

function fileIdentity(file: File) {
  return `${file.name}\u0000${file.size}\u0000${file.lastModified}`;
}

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

function rejectionMessage(rejection: FileRejection) {
  const code = rejection.errors[0]?.code;
  if (code === "file-too-large") return "File is larger than the configured limit.";
  if (code === "file-invalid-type") return "File type is not supported.";
  if (code === "too-many-files") return "Too many files were selected at once.";
  return rejection.errors[0]?.message || "File could not be added.";
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
  onDone: () => void;
  maxMb?: number;
  maxFiles?: number;
}) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [queuePage, setQueuePage] = useState(1);
  const controllers = useRef(new Map<string, AbortController>());
  const uploadProgress = useRef(new Map<string, number>());
  const uploadGeneration = useRef(0);

  const updateItem = useCallback((id: string, patch: Partial<UploadItem>) => {
    setItems((current) => {
      let changed = false;
      const next = current.map((item) => {
        if (item.id !== id) return item;
        const keys = Object.keys(patch) as (keyof UploadItem)[];
        if (keys.every((key) => Object.is(item[key], patch[key]))) return item;
        changed = true;
        return { ...item, ...patch };
      });
      return changed ? next : current;
    });
  }, []);

  const removeItem = useCallback((id: string) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  useEffect(() => {
    const activeControllers = controllers.current;
    const activeProgress = uploadProgress.current;
    uploadGeneration.current += 1;
    activeControllers.forEach((controller) => controller.abort());
    activeControllers.clear();
    activeProgress.clear();
    setItems([]);
    setQueuePage(1);
    setUploading(false);
    return () => {
      uploadGeneration.current += 1;
      activeControllers.forEach((controller) => controller.abort());
      activeControllers.clear();
      activeProgress.clear();
    };
  }, [datasetId]);

  const onDrop = useCallback(
    (acceptedFiles: File[], fileRejections: FileRejection[]) => {
      if (!acceptedFiles.length && !fileRejections.length) return;
      setItems((current) => {
        const hasActiveQueue = current.some((item) => item.status === "queued" || item.status === "uploading");
        const retained = hasActiveQueue ? current : [];
        const known = new Set(retained.map((item) => fileIdentity(item.file)));
        const additions: UploadItem[] = [];
        let uploadableCount = retained.filter((item) => item.status !== "rejected").length;

        for (const file of acceptedFiles) {
          if (uploadableCount >= maxFiles) {
            additions.push({
              id: itemId(file),
              file,
              status: "rejected",
              progress: 0,
              message: `The queue is limited to ${maxFiles} files.`,
              errorCode: "TOO_MANY_FILES",
            });
            continue;
          }
          if (known.has(fileIdentity(file))) {
            additions.push({
              id: itemId(file),
              file,
              status: "rejected",
              progress: 0,
              message: "This file is already in the upload queue.",
              errorCode: "DUPLICATE_SELECTION",
            });
            continue;
          }
          known.add(fileIdentity(file));
          uploadableCount += 1;
          additions.push({ id: itemId(file), file, status: "queued", progress: 0 });
        }
        for (const rejection of fileRejections) {
          additions.push({
            id: itemId(rejection.file),
            file: rejection.file,
            status: "rejected",
            progress: 0,
            message: rejectionMessage(rejection),
            errorCode: rejection.errors[0]?.code.toUpperCase().replaceAll("-", "_") || "CLIENT_REJECTED",
          });
        }
        return [...retained, ...additions];
      });
      if (acceptedFiles.length) announce(`${acceptedFiles.length} file(s) ready to upload`);
      if (fileRejections.length) {
        announce(`${fileRejections.length} file(s) could not be added`, true);
        toast.error(`${fileRejections.length} file(s) did not meet the upload requirements.`);
      }
    },
    [maxFiles],
  );

  const { getRootProps, getInputProps, isDragActive, isDragAccept, isDragReject } = useDropzone({
    onDrop,
    accept: ACCEPT,
    maxFiles,
    maxSize: maxMb * 1_048_576,
    disabled: uploading,
    noClick: true,
    noKeyboard: true,
  });

  const uploadOne = useCallback(
    async (item: UploadItem, generation: number) => {
      if (generation !== uploadGeneration.current) return "cancelled" as const;
      const controller = new AbortController();
      controllers.current.set(item.id, controller);
      uploadProgress.current.set(item.id, 0);
      updateItem(item.id, { status: "uploading", progress: 0, message: undefined, errorCode: undefined });
      const form = new FormData();
      form.append("files", item.file);
      try {
        const response = await http.post<Envelope<UploadResult> | ErrorEnvelope>(
          `/datasets/${datasetId}/upload/`,
          form,
          {
            signal: controller.signal,
            timeout: 0,
            validateStatus: (status) => (status >= 200 && status < 300) || status === 422,
            onUploadProgress: (event) => {
              const total = event.total || item.file.size;
              const progress = total ? Math.min(100, Math.round((event.loaded / total) * 100)) : 0;
              if (uploadProgress.current.get(item.id) === progress) return;
              uploadProgress.current.set(item.id, progress);
              updateItem(item.id, { progress });
            },
          },
        );
        if (generation !== uploadGeneration.current) return "cancelled" as const;
        const envelope = response.data;
        if (!envelope.success) throw new ApiError(response.status, envelope);
        const accepted = envelope.data.accepted[0];
        if (accepted) {
          updateItem(item.id, { status: "accepted", progress: 100, document: accepted });
          return "accepted" as const;
        }
        const rejection = envelope.data.rejected[0];
        updateItem(item.id, {
          status: "rejected",
          progress: 0,
          message: rejection?.message || "The server rejected this file.",
          errorCode: rejection?.error_code || "REJECTED",
        });
        return "rejected" as const;
      } catch (error) {
        if (generation !== uploadGeneration.current) return "cancelled" as const;
        if (isRequestCanceled(error)) {
          updateItem(item.id, { status: "cancelled", progress: 0, message: "Upload cancelled." });
          return "cancelled" as const;
        }
        updateItem(item.id, {
          status: "failed",
          progress: 0,
          message: error instanceof Error ? error.message : "Upload failed. Try this file again.",
          errorCode: error instanceof ApiError ? error.code : "UPLOAD_FAILED",
        });
        return "failed" as const;
      } finally {
        if (controllers.current.get(item.id) === controller) {
          controllers.current.delete(item.id);
          uploadProgress.current.delete(item.id);
        }
      }
    },
    [datasetId, updateItem],
  );

  const startUploads = useCallback(async () => {
    const pending = items.filter((item) => ["queued", "failed", "cancelled"].includes(item.status));
    if (!pending.length || uploading) return;
    const generation = uploadGeneration.current + 1;
    uploadGeneration.current = generation;
    setUploading(true);
    announce(`Uploading ${pending.length} file(s)`);
    let cursor = 0;
    const outcomes: string[] = [];
    const worker = async () => {
      while (cursor < pending.length) {
        const item = pending[cursor];
        cursor += 1;
        outcomes.push(await uploadOne(item, generation));
      }
    };
    await Promise.all(Array.from({ length: Math.min(UPLOAD_CONCURRENCY, pending.length) }, worker));
    if (generation !== uploadGeneration.current) return;
    setUploading(false);
    const accepted = outcomes.filter((outcome) => outcome === "accepted").length;
    const rejected = outcomes.filter((outcome) => outcome === "rejected").length;
    const failed = outcomes.filter((outcome) => outcome === "failed").length;
    if (accepted) {
      onDone();
      toast.success(`${accepted} file(s) accepted.`);
    }
    if (rejected) toast.error(`${rejected} file(s) were rejected. Review the details below.`);
    if (failed) toast.error(`${failed} upload(s) failed and can be retried.`);
    announce(`Upload complete: ${accepted} accepted, ${rejected} rejected, ${failed} failed`);
  }, [items, onDone, uploadOne, uploading]);

  const cancelUploads = useCallback(() => {
    uploadGeneration.current += 1;
    controllers.current.forEach((controller) => controller.abort());
    setUploading(false);
    setItems((current) =>
      current.map((item) =>
        item.status === "queued" || item.status === "uploading"
          ? { ...item, status: "cancelled", progress: 0, message: "Upload cancelled." }
          : item,
      ),
    );
    announce("Uploads cancelled");
  }, []);

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
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() =>
                    setItems((current) => current.filter((item) => !["accepted", "rejected"].includes(item.status)))
                  }
                >
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
