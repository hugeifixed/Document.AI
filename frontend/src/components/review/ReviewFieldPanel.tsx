import { CheckIcon, ExclamationTriangleIcon, XMarkIcon } from "@heroicons/react/20/solid";
import { useRef } from "react";
import { listSummary } from "@/listValues";
import { ListFieldValue } from "./ListFieldValue";
import { checkboxEvidence, fieldDisplayName, fieldDisplayValue } from "@/fieldPresentation";
import type { ExtractedField } from "@/api/types";
import { AsyncButton, ConfidenceCue, StatusChip } from "@/components/ui";

export type FieldAction = "accept" | "correct" | "mark_absent" | "reject" | "promote";
export type FieldScope = "review" | "page" | "all";

type FieldRow = { kind: "heading"; label: string; count: number } | { kind: "field"; field: ExtractedField };

const DECISION_STATUS: Record<Exclude<FieldAction, "promote">, string> = {
  accept: "accepted",
  correct: "corrected",
  mark_absent: "absent",
  reject: "rejected",
};

function isCurrentDecision(field: ExtractedField, action: Exclude<FieldAction, "promote">) {
  return field.review_status === DECISION_STATUS[action];
}

function decisionClass(field: ExtractedField, action: Exclude<FieldAction, "promote">) {
  if (isCurrentDecision(field, action)) return action === "reject" ? "btn-error btn-soft" : "btn-primary btn-soft";
  return action === "reject" ? "btn-ghost text-error" : "btn-outline";
}

function validationMessage(field: ExtractedField, message: string) {
  if (field.field_type === "list" && message.includes("automatic list verification is not available")) {
    return "Check each row against the document. Automated verification isn't available for list fields.";
  }
  return message;
}

function alignActivatedField(button: HTMLButtonElement) {
  const view = button.ownerDocument.defaultView;
  const documentPane = button.ownerDocument.querySelector(".review-document-pane");
  const card = button.closest<HTMLElement>("[data-field-card]");
  if (!view || !documentPane || !card || view.getComputedStyle(documentPane).position !== "sticky") return;

  // Keep the activated card directly below the app header. Avoid restarting a
  // smooth scroll when the user clicks the same field to replay its evidence cue.
  if (Math.abs(card.getBoundingClientRect().top - 96) <= 4) return;
  card.scrollIntoView({
    behavior: view.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    block: "start",
    inline: "nearest",
  });
}

export function ReviewFieldPanel({
  fields,
  scope,
  currentUnit,
  selectedField,
  activeRun,
  documentFailed,
  canReview,
  canApprove,
  pendingAction,
  onSelect,
  onScopeChange,
  onClearSelection,
  onAction,
  onCorrect,
}: {
  fields: ExtractedField[];
  scope: FieldScope;
  currentUnit: number;
  selectedField: string | null;
  activeRun?: string | null;
  documentFailed: boolean;
  canReview: boolean;
  canApprove: boolean;
  pendingAction?: { id: string; action: string };
  onSelect: (id: string) => void;
  onScopeChange: (scope: FieldScope) => void;
  onClearSelection: () => void;
  onAction: (field: ExtractedField, action: Exclude<FieldAction, "correct">) => void;
  onCorrect: (field: ExtractedField) => void;
}) {
  const selectedButton = useRef<HTMLButtonElement>(null);
  const pending = !!pendingAction;
  const isPending = (field: ExtractedField, action: string) =>
    pendingAction?.id === field.id && pendingAction.action === action;
  const needsReview = fields.filter((field) => field.review_status === "needs_review");
  const isOnCurrentPage = (field: ExtractedField) => field.spans.some((span) => span.unit_index === currentUnit);
  const pageFields = fields.filter(isOnCurrentPage);
  const selectedReviewedField = fields.find(
    (field) => field.id === selectedField && field.review_status !== "needs_review",
  );
  const scopeFields = (nextScope: FieldScope) => {
    if (nextScope === "review") return needsReview;
    if (nextScope === "page") return pageFields;
    return fields;
  };
  const changeScope = (nextScope: FieldScope) => {
    if (selectedField && !scopeFields(nextScope).some((field) => field.id === selectedField)) onClearSelection();
    onScopeChange(nextScope);
  };
  const fieldRows: FieldRow[] =
    scope === "review"
      ? [
          {
            label: `On page ${currentUnit + 1}`,
            fields: needsReview.filter(isOnCurrentPage),
          },
          {
            label: "Other pages",
            fields: needsReview.filter((field) => field.spans.length > 0 && !isOnCurrentPage(field)),
          },
          {
            label: "No source location",
            fields: needsReview.filter((field) => field.spans.length === 0),
          },
          {
            label: "Reviewed",
            fields: selectedReviewedField ? [selectedReviewedField] : [],
          },
        ].flatMap(({ label, fields: groupFields }) =>
          groupFields.length
            ? [
                { kind: "heading" as const, label, count: groupFields.length },
                ...groupFields.map((field) => ({ kind: "field" as const, field })),
              ]
            : [],
        )
      : scopeFields(scope).map((field) => ({ kind: "field", field }));
  const emptyMessage =
    scope === "review"
      ? "No fields need review."
      : scope === "page"
        ? `No extracted fields have a source location on page ${currentUnit + 1}.`
        : "No extracted fields are available.";
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2>Fields</h2>
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
        <>
          <p className="mb-3 text-caption text-secondary">
            Confidence reflects the model’s certainty, independently of source verification.
          </p>
          <fieldset className="mb-4">
            <legend className="sr-only">Field scope</legend>
            <div
              className="grid w-full grid-cols-[minmax(0,1.3fr)_minmax(0,1.05fr)_minmax(0,0.65fr)] gap-1 rounded-field bg-base-200 p-1"
              aria-label="Field scope"
            >
              {(
                [
                  ["review", "Needs review", needsReview.length],
                  ["page", "This page", pageFields.length],
                  ["all", "All", fields.length],
                ] as const
              ).map(([value, label, count]) => (
                <button
                  key={value}
                  type="button"
                  className={`flex min-h-11 min-w-0 items-center justify-center gap-1.5 rounded-field px-2 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${
                    scope === value
                      ? "bg-primary text-primary-content shadow-sm"
                      : "text-secondary hover:bg-base-100 hover:text-base-content"
                  }`}
                  aria-pressed={scope === value}
                  onClick={() => changeScope(value)}
                >
                  <span className="whitespace-nowrap">{label}</span>
                  <span
                    className={`badge badge-sm shrink-0 tabular-nums ${
                      scope === value
                        ? "border-primary-content/20 bg-primary-content/15 text-primary-content"
                        : "badge-ghost"
                    }`}
                  >
                    {count}
                  </span>
                </button>
              ))}
            </div>
          </fieldset>
        </>
      )}
      {!activeRun && <p className="text-sm">No run has processed this document yet.</p>}
      {documentFailed && fields.length === 0 && (
        <p className="text-sm">No reviewable fields were produced before this document failed.</p>
      )}
      {fields.length > 0 && fieldRows.length === 0 && <p className="text-sm text-secondary">{emptyMessage}</p>}
      <ul className="space-y-2">
        {fieldRows.map((row) => {
          if (row.kind === "heading") {
            return (
              <li key={`heading-${row.label}`} className="flex items-center gap-2 px-1 pt-2 first:pt-0">
                <h3 className="text-caption font-semibold text-secondary">{row.label}</h3>
                <span className="badge badge-ghost badge-sm tabular-nums">{row.count}</span>
              </li>
            );
          }
          const field = row.field;
          return (
            <li
              key={field.id}
              data-field-card
              className={`scroll-mt-24 rounded-box border p-2 ${selectedField === field.id ? "bg-(--color-blue-soft) ring-2 ring-primary" : ""} border-base-300`}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <button
                  type="button"
                  ref={selectedField === field.id ? selectedButton : undefined}
                  className="min-h-11 min-w-0 flex-1 cursor-pointer rounded-field p-2 text-left [overflow-wrap:anywhere] hover:bg-(--color-blue-soft)"
                  onClick={(event) => {
                    onSelect(field.id);
                    alignActivatedField(event.currentTarget);
                  }}
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
                  <ConfidenceCue
                    score={field.score}
                    status={field.review_status}
                    label={fieldDisplayName(field.name)}
                  />
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
                  <span className="font-medium text-base-content">Evidence:</span> “{field.source_text.slice(0, 80)}”
                  {field.spans[0]
                    ? ` · p${field.spans[0].unit_index + 1} · ${field.spans[0].mapping_method}`
                    : " · no source location"}
                </div>
              ) : null}
              {field.validation_messages.length > 0 && (
                <div className="alert alert-soft alert-warning mx-2 mt-2 items-start gap-2 p-3 text-sm">
                  <ExclamationTriangleIcon className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
                  <div className="min-w-0 [overflow-wrap:anywhere]">
                    <p className="font-medium">Review needed</p>
                    <ul className="mt-1 space-y-1">
                      {field.validation_messages.map((message, index) => (
                        <li key={index}>{validationMessage(field, message)}</li>
                      ))}
                    </ul>
                    {field.suggested_correction && (
                      <p className="mt-2">
                        Suggested value:{" "}
                        <span className="font-mono">{fieldDisplayValue(field, field.suggested_correction)}</span>
                      </p>
                    )}
                  </div>
                </div>
              )}
              {(canReview || (["accepted", "corrected", "absent"].includes(field.review_status) && canApprove)) && (
                <div className="mx-2 mt-3 border-t border-base-300 pt-3">
                  {canReview && (
                    <fieldset>
                      <legend className="mb-2 text-caption font-semibold text-secondary">
                        {field.review_status === "needs_review" ? "Review decision" : "Change review decision"}
                      </legend>
                      <div className="grid grid-cols-2 gap-2">
                        <AsyncButton
                          className={"btn btn-sm min-h-11 sm:min-h-10 " + decisionClass(field, "accept")}
                          pending={isPending(field, "accept")}
                          pendingLabel="Accepting…"
                          disabled={pending}
                          aria-pressed={isCurrentDecision(field, "accept")}
                          onClick={() => onAction(field, "accept")}
                        >
                          <span className="inline-flex items-center justify-center gap-1.5">
                            {isCurrentDecision(field, "accept") && <CheckIcon className="size-4" aria-hidden="true" />}
                            Accept value
                          </span>
                        </AsyncButton>
                        <button
                          type="button"
                          className={"btn btn-sm min-h-11 sm:min-h-10 " + decisionClass(field, "correct")}
                          disabled={pending}
                          aria-pressed={isCurrentDecision(field, "correct")}
                          aria-haspopup="dialog"
                          onClick={() => onCorrect(field)}
                        >
                          {isCurrentDecision(field, "correct") && <CheckIcon className="size-4" aria-hidden="true" />}
                          Correct value
                        </button>
                        <AsyncButton
                          className={"btn btn-sm min-h-11 sm:min-h-10 " + decisionClass(field, "mark_absent")}
                          pending={isPending(field, "mark_absent")}
                          pendingLabel="Saving…"
                          disabled={pending}
                          aria-pressed={isCurrentDecision(field, "mark_absent")}
                          onClick={() => onAction(field, "mark_absent")}
                        >
                          <span className="inline-flex items-center justify-center gap-1.5">
                            {isCurrentDecision(field, "mark_absent") && (
                              <CheckIcon className="size-4" aria-hidden="true" />
                            )}
                            Mark absent
                          </span>
                        </AsyncButton>
                        <button
                          type="button"
                          className={"btn btn-sm min-h-11 sm:min-h-10 " + decisionClass(field, "reject")}
                          disabled={pending}
                          aria-pressed={isCurrentDecision(field, "reject")}
                          aria-haspopup="dialog"
                          onClick={() => onAction(field, "reject")}
                        >
                          {isCurrentDecision(field, "reject") && <CheckIcon className="size-4" aria-hidden="true" />}
                          Reject result
                        </button>
                      </div>
                    </fieldset>
                  )}
                  {["accepted", "corrected", "absent"].includes(field.review_status) && canApprove && (
                    <div className="mt-3 flex flex-col items-start gap-3 rounded-field bg-base-200 p-3 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <p className="text-sm font-semibold">Ground truth</p>
                        <p className="mt-1 text-caption text-secondary">
                          Use this reviewed value as the expected answer in evaluations.
                        </p>
                      </div>
                      <button
                        type="button"
                        className="btn btn-sm btn-primary min-h-11 w-full shrink-0 sm:min-h-10 sm:w-auto"
                        disabled={pending}
                        aria-label="Promote to ground truth"
                        aria-haspopup="dialog"
                        onClick={() => onAction(field, "promote")}
                      >
                        Promote
                      </button>
                    </div>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
