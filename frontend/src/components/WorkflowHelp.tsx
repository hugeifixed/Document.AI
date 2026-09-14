import { InformationCircleIcon } from "@heroicons/react/20/solid";
import { type ReactNode, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { ScrollRegion } from "@/components/ui";

/** Read-only help stays outside the builder form and preserves its draft and validation. */
function HelpDialog({
  label,
  title,
  intro,
  children,
}: {
  label: string;
  title: string;
  intro: string;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const id = useId();
  return (
    <>
      <button
        type="button"
        className="btn btn-ghost btn-square size-11 shrink-0 text-primary sm:size-10"
        aria-label={label}
        aria-haspopup="dialog"
        aria-controls={id}
        onClick={() => {
          dialog.current?.showModal();
          heading.current?.focus();
        }}
      >
        <InformationCircleIcon className="size-5" aria-hidden="true" />
      </button>
      {createPortal(
        <dialog
          ref={dialog}
          id={id}
          className="modal p-4"
          aria-labelledby={`${id}-title`}
          aria-describedby={`${id}-intro`}
        >
          <div className="modal-box flex max-h-[calc(100dvh-2rem)] w-full max-w-2xl flex-col gap-4 overflow-hidden border border-base-300 p-4 sm:p-5">
            <header className="shrink-0">
              <h2 ref={heading} id={`${id}-title`} tabIndex={-1} className="text-section-title">
                {title}
              </h2>
              <p id={`${id}-intro`} className="mt-2 text-sm text-secondary">
                {intro}
              </p>
            </header>
            <ScrollRegion label={`${title} guidance`} className="min-h-0 text-sm [overflow-wrap:anywhere]">
              {children}
            </ScrollRegion>
            <form method="dialog" className="modal-action m-0 shrink-0" onSubmit={(event) => event.stopPropagation()}>
              <button className="btn btn-outline min-h-11 sm:min-h-10">Close</button>
            </form>
          </div>
        </dialog>,
        document.body,
      )}
    </>
  );
}

const WORKFLOW_GUIDANCE: Record<string, { title: string; description: string }> = {
  unbundle_classify_extract: {
    title: "Unbundle, classify and extract",
    description:
      "Use for packets containing multiple documents or form types, such as W-2s and 1099s together. Identify page groups, classify each group, and extract the fields defined for its category.",
  },
  classify_structured: {
    title: "Classify structured documents",
    description:
      "Use when form numbers, titles or known phrases reliably identify a document. Rules assign a category, with optional LLM fallback; this does not extract fields.",
  },
  classify_unstructured: {
    title: "Classify unstructured documents",
    description:
      "Use when meaning matters more than a fixed layout, such as distinguishing correspondence from agreements. The LLM chooses from your categories; this does not extract fields.",
  },
  extract_structured: {
    title: "Extract structured documents",
    description:
      "Use for a known form such as a W-2. Default mode discovers key-value pairs; custom mode extracts the fields you define in a schema. For consistent W-2 boxes, use custom mode and list the required fields in the type-specific JSON.",
  },
  extract_unstructured: {
    title: "Extract unstructured documents",
    description:
      "Use for facts embedded in prose, such as a borrower and principal amount in a promissory note. Define the fields in a schema; evidence is located in the document and results are reconciled across chunks.",
  },
  extract_template: {
    title: "Extract with a template",
    description:
      "Use when a reusable, versioned extraction template already defines the schema, prompt and field guidance. Reference its name and version to keep repeated runs consistent.",
  },
};

export function WorkflowTypeHelp({ types }: { types?: Record<string, { label: string }> }) {
  return (
    <HelpDialog
      label="About workflow types"
      title="Choose a workflow type"
      intro="Choose by the output you need: categories, extracted fields, or both."
    >
      <dl className="grid gap-4">
        {Object.entries(WORKFLOW_GUIDANCE)
          .filter(([key]) => !types || key in types)
          .map(([key, help]) => (
            <div key={key}>
              <dt className="font-semibold">{types?.[key]?.label ?? help.title}</dt>
              <dd className="mt-2 text-secondary">{help.description}</dd>
            </div>
          ))}
      </dl>
    </HelpDialog>
  );
}

export const CHUNK_STRATEGIES = {
  whole_document: "Whole document",
  page: "Per page",
  sheet: "Per sheet",
  context_length: "Character windows",
  semantic: "Section-aware (semantic)",
};

const CHUNK_GUIDANCE: Record<keyof typeof CHUNK_STRATEGIES, string> = {
  whole_document:
    "Start here for short documents or when fields depend on context across pages. Keeps the selected content together until the configured whole-document limit is exceeded.",
  page: "Use when each page is self-contained, such as one form per page. Information that continues onto another page may lose context.",
  sheet:
    "Use for spreadsheets whose worksheets can be interpreted independently. A large worksheet is still sent as one chunk.",
  context_length:
    "Use for long documents. Splits preserved text into character-sized windows with optional overlap; boundaries can cut across sections.",
  semantic:
    "Use for narrative documents with paragraphs and headings. Groups text at those boundaries; a long section can exceed the target size. This does not use embeddings or another model call.",
};

export function ChunkingHelp({ workflowType }: { workflowType: string }) {
  return (
    <HelpDialog
      label="About chunking"
      title="Choose how to split content"
      intro="Chunking divides one document’s text for model calls. It does not control how many files process at once."
    >
      {workflowType === "classify_structured" && (
        <p className="mb-4">
          Rule-based classification does not use these chunking settings, including its LLM fallback.
        </p>
      )}
      {workflowType === "extract_template" && (
        <p className="mb-4">The selected template’s chunking settings take precedence when supplied.</p>
      )}
      <dl className="grid gap-4">
        {Object.entries(CHUNK_GUIDANCE).map(([key, description]) => (
          <div key={key}>
            <dt className="font-semibold">{CHUNK_STRATEGIES[key as keyof typeof CHUNK_STRATEGIES]}</dt>
            <dd className="mt-2 text-secondary">{description}</dd>
          </div>
        ))}
        <div className="border-t border-base-300 pt-4">
          <dt className="font-semibold">Size and overlap</dt>
          <dd className="mt-2 text-secondary">
            These apply to character windows and section-aware chunks. Size is a character target, not a token limit;
            overlap repeats preceding text to retain context and increases model input.
          </dd>
        </div>
        <div>
          <dt className="font-semibold">Fallback</dt>
          <dd className="mt-2 text-secondary">
            Used only when Whole document exceeds its configured character limit, and recorded in the run. None stops
            that document with a limit error. It does not retry Azure errors or fix truncated model output.
          </dd>
        </div>
      </dl>
    </HelpDialog>
  );
}
