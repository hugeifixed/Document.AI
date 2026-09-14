import { XMarkIcon } from "@heroicons/react/20/solid";
import { useRef } from "react";
import { listSummary } from "@/listValues";
import { ListFieldValue } from "./ListFieldValue";
import { checkboxEvidence, fieldDisplayName, fieldDisplayValue } from "@/fieldPresentation";
import type { ExtractedField } from "@/api/types";
import { AsyncButton, ConfidenceCue, StatusChip } from "@/components/ui";

export type FieldAction = "accept" | "correct" | "mark_absent" | "reject" | "promote";

export function ReviewFieldPanel({
  fields,
  selectedField,
  activeRun,
  documentFailed,
  canReview,
  canApprove,
  pendingAction,
  onSelect,
  onClearSelection,
  onAction,
  onCorrect,
}: {
  fields: ExtractedField[];
  selectedField: string | null;
  activeRun?: string | null;
  documentFailed: boolean;
  canReview: boolean;
  canApprove: boolean;
  pendingAction?: { id: string; action: string };
  onSelect: (id: string) => void;
  onClearSelection: () => void;
  onAction: (field: ExtractedField, action: Exclude<FieldAction, "correct">) => void;
  onCorrect: (field: ExtractedField) => void;
}) {
  const selectedButton = useRef<HTMLButtonElement>(null);
  const pending = !!pendingAction;
  const isPending = (field: ExtractedField, action: string) =>
    pendingAction?.id === field.id && pendingAction.action === action;
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2>Fields ({fields.length})</h2>
        {fields.length > 0 && (
          <button
            type="button"
            className="btn btn-ghost btn-sm min-h-11 sm:min-h-10"
            disabled={!selectedField}
            onClick={() => {
              selectedButton.current?.focus();
              onClearSelection();
            }}
          >
            <XMarkIcon className="size-5" aria-hidden="true" />
            Clear selection
          </button>
        )}
      </div>
      {fields.length > 0 && (
        <p className="mb-2 text-caption text-secondary">
          Confidence reflects the model’s certainty, independently of source verification.
        </p>
      )}
      {!activeRun && <p className="text-sm">No run has processed this document yet.</p>}
      {documentFailed && fields.length === 0 && (
        <p className="text-sm">No reviewable fields were produced before this document failed.</p>
      )}
      <ul className="space-y-2">
        {fields.map((field) => (
          <li
            key={field.id}
            className={`rounded-box border p-2 ${selectedField === field.id ? "bg-(--color-blue-soft) ring-2 ring-primary" : ""} border-base-300`}
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <button
                type="button"
                ref={selectedField === field.id ? selectedButton : undefined}
                className="min-h-11 min-w-0 flex-1 cursor-pointer rounded-field p-2 text-left [overflow-wrap:anywhere] hover:bg-(--color-blue-soft)"
                onClick={() => onSelect(field.id)}
                aria-pressed={selectedField === field.id}
              >
                <div className="text-sm font-semibold text-primary underline underline-offset-2">
                  {fieldDisplayName(field.name)}
                </div>
                <div className="font-mono text-sm">
                  {(field.field_type === "list"
                    ? listSummary(field.reviewed_value ?? field.raw_value)
                    : fieldDisplayValue(field, field.reviewed_value ?? field.raw_value)) ?? (
                    <em className="text-secondary">not found</em>
                  )}
                </div>
              </button>
              <div className="ml-auto p-2 text-right">
                <ConfidenceCue score={field.score} status={field.review_status} label={fieldDisplayName(field.name)} />
                <div>
                  <StatusChip status={field.review_status} />
                </div>
              </div>
            </div>
            {field.field_type === "list" && (
              <div className="min-w-0 max-w-full px-2 py-2">
                <ListFieldValue value={field.reviewed_value ?? field.raw_value} name={fieldDisplayName(field.name)} />
                {Array.isArray(field.list_candidates) && field.list_candidates.length > 0 && (
                  <details className="mt-2 rounded-field border border-base-300 p-2">
                    <summary className="cursor-pointer text-sm text-primary">
                      Compare chunk alternatives ({field.list_candidates.length})
                    </summary>
                    <div className="mt-2 space-y-4">
                      {field.list_candidates.map((candidate, index) => (
                        <div key={index}>
                          <p className="mb-2 text-caption text-secondary">Alternative {index + 1}</p>
                          <ListFieldValue value={candidate.value} name={`${field.name} alternative ${index + 1}`} />
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            )}
            {checkboxEvidence(field) ? (
              <div className="mt-1 px-2 text-caption text-secondary">{checkboxEvidence(field)}</div>
            ) : field.source_text ? (
              <div className="mt-1 px-2 text-caption text-secondary">
                evidence: “{field.source_text.slice(0, 80)}”
                {field.spans[0]
                  ? ` · p${field.spans[0].unit_index + 1} · ${field.spans[0].mapping_method}`
                  : " · not grounded"}
              </div>
            ) : null}
            {field.validation_messages.length > 0 && (
              <div className="mt-1 px-2 text-caption text-warning">
                {field.validation_messages.join("; ")}
                {field.suggested_correction && (
                  <>
                    {" "}
                    · suggested:{" "}
                    <span className="font-mono">{fieldDisplayValue(field, field.suggested_correction)}</span>
                  </>
                )}
              </div>
            )}
            <div className="mt-2 flex flex-wrap gap-1 px-2">
              {canReview && (
                <>
                  <AsyncButton
                    className="btn btn-xs btn-outline"
                    pending={isPending(field, "accept")}
                    pendingLabel="Accepting…"
                    disabled={pending}
                    onClick={() => onAction(field, "accept")}
                  >
                    Accept
                  </AsyncButton>
                  <button
                    type="button"
                    className="btn btn-xs btn-outline"
                    disabled={pending}
                    aria-haspopup="dialog"
                    onClick={() => onCorrect(field)}
                  >
                    Correct
                  </button>
                  <AsyncButton
                    className="btn btn-xs btn-outline"
                    pending={isPending(field, "mark_absent")}
                    pendingLabel="Saving…"
                    disabled={pending}
                    onClick={() => onAction(field, "mark_absent")}
                  >
                    Absent
                  </AsyncButton>
                  <button
                    type="button"
                    className="btn btn-xs btn-ghost"
                    disabled={pending}
                    aria-haspopup="dialog"
                    onClick={() => onAction(field, "reject")}
                  >
                    Reject
                  </button>
                </>
              )}
              {["accepted", "corrected", "absent"].includes(field.review_status) && canApprove && (
                <button
                  type="button"
                  className="btn btn-xs btn-primary"
                  disabled={pending}
                  aria-haspopup="dialog"
                  onClick={() => onAction(field, "promote")}
                >
                  Promote to ground truth
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
