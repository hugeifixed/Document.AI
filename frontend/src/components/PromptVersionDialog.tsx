import { ClipboardDocumentIcon } from "@heroicons/react/20/solid";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";
import { list } from "@/common/api/client";
import type { PromptVersion, PromptVersionReference } from "@/common/types/api";
import { ErrorNotice } from "@/components/ErrorNotice";

const STAGE_LABELS: Record<string, string> = {
  segmentation: "Segmentation",
  classification: "Classification",
  extraction: "Extraction",
  generic_kv: "Generic key/value extraction",
};

export function promptStageLabel(stage: string) {
  return STAGE_LABELS[stage] ?? stage.replace(/_/g, " ");
}

async function copyPrompt(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`${label} copied`);
  } catch {
    toast.error(`Could not copy ${label.toLowerCase()}`);
  }
}

function PromptText({ title, value }: { title: string; value: string }) {
  return (
    <section>
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">{title}</h3>
        <button type="button" className="btn btn-ghost btn-sm min-h-10" onClick={() => void copyPrompt(value, title)}>
          <ClipboardDocumentIcon className="size-4" aria-hidden="true" />
          Copy
        </button>
      </div>
      <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-box border border-base-300 bg-base-200 p-4 font-mono text-sm [overflow-wrap:anywhere]">
        {value}
      </pre>
    </section>
  );
}

export function PromptVersionDialog({
  stage,
  reference,
  onClose,
}: {
  stage: string | null;
  reference: PromptVersionReference | null;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const id = useId();
  const query = useQuery({
    queryKey: ["prompt-version", reference?.name, reference?.version],
    queryFn: async ({ signal }) => {
      const page = await list<PromptVersion>(
        "/prompts/",
        { name: reference!.name, version: reference!.version, page_size: 1 },
        { signal },
      );
      return page.results[0] ?? null;
    },
    enabled: reference !== null,
  });

  useEffect(() => {
    if (reference && !dialog.current?.open) {
      dialog.current?.showModal();
      heading.current?.focus();
    } else if (!reference && dialog.current?.open) {
      dialog.current.close();
    }
  }, [reference]);

  if (!stage) return null;
  const prompt = query.data;
  return createPortal(
    <dialog
      ref={dialog}
      className="modal p-4"
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-privacy`}
      onClose={onClose}
    >
      <div className="modal-box flex max-h-[calc(100dvh-2rem)] w-full max-w-4xl flex-col overflow-hidden border border-base-300 p-0">
        <header className="shrink-0 border-b border-base-300 p-4 sm:p-5">
          <h2 ref={heading} id={`${id}-title`} tabIndex={-1} className="text-section-title capitalize">
            {promptStageLabel(stage)} prompt
          </h2>
          <p className="mt-1 font-mono text-sm text-secondary">
            {reference?.name}@{reference?.version}
          </p>
        </header>
        <div className="min-h-0 space-y-5 overflow-y-auto p-4 sm:p-5">
          {query.isLoading && <output className="block text-sm text-secondary">Loading prompt definition…</output>}
          {query.error && (
            <ErrorNotice message="The prompt definition could not be loaded." onRetry={() => void query.refetch()} />
          )}
          {!query.isLoading && !query.error && !prompt && (
            <p className="text-sm text-secondary">This prompt definition is no longer available.</p>
          )}
          {prompt && (
            <>
              <dl className="grid gap-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-secondary">Purpose</dt>
                  <dd className="mt-1">{prompt.purpose}</dd>
                </div>
                <div>
                  <dt className="text-secondary">Content hash</dt>
                  <dd className="mt-1 break-all font-mono text-caption">{prompt.content_hash}</dd>
                </div>
              </dl>
              <PromptText title="System instructions" value={prompt.system_prompt} />
              <PromptText title="User template" value={prompt.user_template} />
            </>
          )}
          <p id={`${id}-privacy`} className="alert alert-soft alert-info text-sm">
            This is the immutable prompt template. Values rendered from a document are never shown here.
          </p>
        </div>
        <form method="dialog" className="modal-action m-0 shrink-0 border-t border-base-300 p-4 sm:p-5">
          <button className="btn btn-outline min-h-11 sm:min-h-10">Close</button>
        </form>
      </div>
    </dialog>,
    document.body,
  );
}
