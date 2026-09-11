import { useCallback, useEffect, useReducer, useRef } from "react";
import type { FileRejection } from "react-dropzone";
import { toast } from "sonner";
import { announce } from "@/a11y/announce";
import { ApiError, http, isRequestCanceled } from "@/api/client";
import type { Document, Envelope, ErrorEnvelope } from "@/api/types";

const UPLOAD_CONCURRENCY = 2;

export type UploadStatus = "queued" | "uploading" | "accepted" | "rejected" | "failed" | "cancelled";
type UploadRejection = { filename: string; message: string; error_code: string; errors?: Record<string, unknown> };
type UploadResult = { accepted: Document[]; rejected: UploadRejection[] };
export type UploadItem = {
  id: string;
  file: File;
  status: UploadStatus;
  progress: number;
  message?: string;
  errorCode?: string;
  document?: Document;
};

type Candidate = {
  id: string;
  file: File;
  rejection?: { message: string; errorCode: string };
};
type QueueState = { items: UploadItem[]; uploading: boolean };
type QueueAction =
  | { type: "reset" }
  | { type: "add"; candidates: Candidate[]; maxFiles: number }
  | { type: "update"; id: string; patch: Partial<UploadItem> }
  | { type: "remove"; id: string }
  | { type: "start" }
  | { type: "finish" }
  | { type: "cancel" }
  | { type: "clear-completed" };

let uploadSequence = 0;

function itemId(file: File) {
  uploadSequence += 1;
  return [file.name, file.size, file.lastModified, uploadSequence].join("-");
}

function fileIdentity(file: File) {
  return [file.name, file.size, file.lastModified].join("\u0000");
}

export function rejectionMessage(rejection: FileRejection) {
  const code = rejection.errors[0]?.code;
  if (code === "file-too-large") return "File is larger than the configured limit.";
  if (code === "file-invalid-type") return "File type is not supported.";
  if (code === "too-many-files") return "Too many files were selected at once.";
  return rejection.errors[0]?.message || "File could not be added.";
}

function queueReducer(state: QueueState, action: QueueAction): QueueState {
  if (action.type === "reset") return { items: [], uploading: false };
  if (action.type === "start") return state.uploading ? state : { ...state, uploading: true };
  if (action.type === "finish") return state.uploading ? { ...state, uploading: false } : state;
  if (action.type === "remove") return { ...state, items: state.items.filter((item) => item.id !== action.id) };
  if (action.type === "clear-completed") {
    return { ...state, items: state.items.filter((item) => !["accepted", "rejected"].includes(item.status)) };
  }
  if (action.type === "cancel") {
    return {
      uploading: false,
      items: state.items.map((item) =>
        item.status === "queued" || item.status === "uploading"
          ? { ...item, status: "cancelled", progress: 0, message: "Upload cancelled." }
          : item,
      ),
    };
  }
  if (action.type === "update") {
    let changed = false;
    const items = state.items.map((item) => {
      if (item.id !== action.id) return item;
      const keys = Object.keys(action.patch) as (keyof UploadItem)[];
      if (keys.every((key) => Object.is(item[key], action.patch[key]))) return item;
      changed = true;
      return { ...item, ...action.patch };
    });
    return changed ? { ...state, items } : state;
  }

  const hasActiveQueue = state.items.some((item) => item.status === "queued" || item.status === "uploading");
  const retained = hasActiveQueue ? state.items : [];
  const known = new Set(retained.map((item) => fileIdentity(item.file)));
  let uploadableCount = retained.filter((item) => item.status !== "rejected").length;
  const additions: UploadItem[] = action.candidates.map((candidate) => {
    if (candidate.rejection) {
      return {
        id: candidate.id,
        file: candidate.file,
        status: "rejected",
        progress: 0,
        message: candidate.rejection.message,
        errorCode: candidate.rejection.errorCode,
      };
    }
    if (uploadableCount >= action.maxFiles) {
      return {
        id: candidate.id,
        file: candidate.file,
        status: "rejected",
        progress: 0,
        message: "The queue is limited to " + action.maxFiles + " files.",
        errorCode: "TOO_MANY_FILES",
      };
    }
    const identity = fileIdentity(candidate.file);
    if (known.has(identity)) {
      return {
        id: candidate.id,
        file: candidate.file,
        status: "rejected",
        progress: 0,
        message: "This file is already in the upload queue.",
        errorCode: "DUPLICATE_SELECTION",
      };
    }
    known.add(identity);
    uploadableCount += 1;
    return { id: candidate.id, file: candidate.file, status: "queued", progress: 0 };
  });
  return { ...state, items: [...retained, ...additions] };
}

export function useUploadQueue({
  datasetId,
  onDone,
  maxFiles,
}: {
  datasetId: string;
  onDone: () => void;
  maxFiles: number;
}) {
  const [{ items, uploading }, dispatch] = useReducer(queueReducer, { items: [], uploading: false });
  const controllers = useRef(new Map<string, AbortController>());
  const uploadProgress = useRef(new Map<string, number>());
  const uploadGeneration = useRef(0);
  const starting = useRef(false);

  const updateItem = useCallback((id: string, patch: Partial<UploadItem>) => {
    dispatch({ type: "update", id, patch });
  }, []);

  useEffect(() => {
    const activeControllers = controllers.current;
    const activeProgress = uploadProgress.current;
    uploadGeneration.current += 1;
    starting.current = false;
    activeControllers.forEach((controller) => controller.abort());
    activeControllers.clear();
    activeProgress.clear();
    dispatch({ type: "reset" });
    return () => {
      uploadGeneration.current += 1;
      starting.current = false;
      activeControllers.forEach((controller) => controller.abort());
      activeControllers.clear();
      activeProgress.clear();
    };
  }, [datasetId]);

  const addFiles = useCallback(
    (acceptedFiles: File[], fileRejections: FileRejection[]) => {
      if (!acceptedFiles.length && !fileRejections.length) return;
      const candidates: Candidate[] = [
        ...acceptedFiles.map((file) => ({ id: itemId(file), file })),
        ...fileRejections.map((rejection) => ({
          id: itemId(rejection.file),
          file: rejection.file,
          rejection: {
            message: rejectionMessage(rejection),
            errorCode: rejection.errors[0]?.code.toUpperCase().replaceAll("-", "_") || "CLIENT_REJECTED",
          },
        })),
      ];
      dispatch({ type: "add", candidates, maxFiles });
      if (acceptedFiles.length) announce(acceptedFiles.length + " file(s) ready to upload");
      if (fileRejections.length) {
        announce(fileRejections.length + " file(s) could not be added", true);
        toast.error(fileRejections.length + " file(s) did not meet the upload requirements.");
      }
    },
    [maxFiles],
  );

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
          "/datasets/" + datasetId + "/upload/",
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
    if (!pending.length || starting.current) return;
    starting.current = true;
    const generation = uploadGeneration.current + 1;
    uploadGeneration.current = generation;
    dispatch({ type: "start" });
    announce("Uploading " + pending.length + " file(s)");
    let cursor = 0;
    const outcomes: string[] = [];
    const worker = async () => {
      while (cursor < pending.length) {
        const item = pending[cursor];
        cursor += 1;
        outcomes.push(await uploadOne(item, generation));
      }
    };
    try {
      await Promise.all(Array.from({ length: Math.min(UPLOAD_CONCURRENCY, pending.length) }, worker));
      if (generation !== uploadGeneration.current) return;
      const accepted = outcomes.filter((outcome) => outcome === "accepted").length;
      const rejected = outcomes.filter((outcome) => outcome === "rejected").length;
      const failed = outcomes.filter((outcome) => outcome === "failed").length;
      if (accepted) {
        onDone();
        toast.success(accepted + " file(s) accepted.");
      }
      if (rejected) toast.error(rejected + " file(s) were rejected. Review the details below.");
      if (failed) toast.error(failed + " upload(s) failed and can be retried.");
      announce("Upload complete: " + accepted + " accepted, " + rejected + " rejected, " + failed + " failed");
    } finally {
      if (generation === uploadGeneration.current) {
        starting.current = false;
        dispatch({ type: "finish" });
      }
    }
  }, [items, onDone, uploadOne]);

  const cancelUploads = useCallback(() => {
    uploadGeneration.current += 1;
    starting.current = false;
    controllers.current.forEach((controller) => controller.abort());
    dispatch({ type: "cancel" });
    announce("Uploads cancelled");
  }, []);

  return {
    items,
    uploading,
    addFiles,
    removeItem: useCallback((id: string) => dispatch({ type: "remove", id }), []),
    clearCompleted: useCallback(() => dispatch({ type: "clear-completed" }), []),
    startUploads,
    cancelUploads,
  };
}
