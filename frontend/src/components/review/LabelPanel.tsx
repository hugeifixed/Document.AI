import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { apiFieldError, errorMessage, post } from "@/api/client";
import type { Label } from "@/api/types";
import { AsyncButton, Field, StatusChip } from "@/components/ui";
import type { GroundTruthLabelRequest, GroundTruthSelectionController } from "@/groundTruth/selection";
import { useWorkspaceDraft } from "@/workspace/navigation";

const labelSchema = z.object({
  fieldName: z.string().refine((value) => value.trim().length > 0, "Enter a field name."),
  expected: z.string(),
  notes: z.string(),
});
type LabelForm = z.infer<typeof labelSchema>;

export function LabelPanel({
  selection,
  schemaFields,
  labels,
  disabled = false,
}: {
  selection: GroundTruthSelectionController;
  schemaFields: string[];
  labels: Label[];
  disabled?: boolean;
}) {
  const qc = useQueryClient();
  const {
    register,
    handleSubmit,
    setError,
    setValue,
    clearErrors,
    reset,
    getValues,
    formState: { errors, isDirty },
  } = useForm<LabelForm>({
    resolver: zodResolver(labelSchema),
    defaultValues: { fieldName: "", expected: "", notes: "" },
  });

  useEffect(() => {
    if (selection.value.pdfText) setValue("expected", selection.value.pdfText.text, { shouldDirty: true });
  }, [selection.value.pdfText, setValue]);
  useEffect(() => {
    clearErrors("root.selection");
  }, [clearErrors, selection.value.cellRange, selection.value.pdfText, selection.value.wordIds]);

  const applyServerErrors = (error: unknown) => {
    for (const [serverName, formName] of [
      ["field_name", "fieldName"],
      ["expected_value", "expected"],
      ["notes", "notes"],
    ] as const) {
      const message = apiFieldError(error, serverName);
      if (message) setError(formName, { type: "server", message });
    }
    const selectionMessage = ["cell_range", "word_ids", "rects", "text", "unit_index"]
      .map((field) => apiFieldError(error, field))
      .find(Boolean);
    if (selectionMessage) setError("root.selection", { type: "server", message: selectionMessage });
    toast.error(errorMessage(error));
  };

  const evidenceFingerprint = JSON.stringify([
    selection.value.mode,
    selection.value.pdfText,
    selection.value.wordIds,
    selection.value.cellRange,
  ]);
  const createLabel = useMutation({
    mutationFn: ({
      request,
    }: {
      request: GroundTruthLabelRequest;
      values: LabelForm;
      evidence: string;
      resetSelection: GroundTruthSelectionController["reset"];
    }) => post<Label>("/labels/", request),
    onSuccess: (label, { request, values, evidence, resetSelection }) => {
      if (request.mode === "absent") toast.success("Marked absent");
      else
        toast.success(
          "Label saved · " +
            label.mapping_method +
            " (" +
            (label.match_score != null ? Math.round(label.match_score * 100) + "%" : "n/a") +
            ")" +
            (label.mapping_exceptions.length ? " — " + label.mapping_exceptions[0] : ""),
        );
      const current = getValues();
      // Preserve the next draft if text or document evidence changed while this label was saving.
      const unchanged =
        current.fieldName === values.fieldName &&
        current.expected === values.expected &&
        current.notes === values.notes &&
        evidenceFingerprint === evidence &&
        selection.reset === resetSelection;
      reset({ fieldName: request.field_name, expected: "", notes: request.notes });
      if (unchanged) selection.reset();
      else {
        for (const key of ["fieldName", "expected", "notes"] as const)
          setValue(key, current[key], { shouldDirty: true });
      }
      qc.invalidateQueries({ queryKey: ["labels", request.document] });
    },
    onError: applyServerErrors,
  });
  const hasEvidence = !!selection.value.pdfText || selection.value.wordIds.length > 0 || !!selection.value.cellRange;
  useWorkspaceDraft(isDirty || hasEvidence, createLabel.isPending);

  const submit = (values: LabelForm, intent: "save" | "absent") => {
    clearErrors("root");
    const prepared = selection.prepareLabel(
      { fieldName: values.fieldName, expectedValue: values.expected, notes: values.notes },
      intent,
    );
    if (!prepared.ok) {
      toast.error(prepared.error.message);
      return;
    }
    createLabel.mutate({
      request: prepared.request,
      values,
      evidence: evidenceFingerprint,
      resetSelection: selection.reset,
    });
  };
  const selectionError = selection.value.error?.message ?? errors.root?.selection?.message;

  return (
    <form className="space-y-4" onSubmit={handleSubmit((values) => submit(values, "save"))}>
      <h2>New label</h2>
      <Field id="reviewworkspace-field-name" label="Field name" required>
        <input
          id="reviewworkspace-field-name"
          className={"input input-sm w-full border-(--border-interactive) " + (errors.fieldName ? "input-error" : "")}
          list="schema-fields"
          {...register("fieldName")}
          required
          aria-invalid={!!errors.fieldName}
          aria-describedby={errors.fieldName ? "reviewworkspace-field-name-error" : undefined}
        />
        <datalist id="schema-fields">
          {schemaFields.map((field) => (
            <option key={field} value={field}>
              {field}
            </option>
          ))}
        </datalist>
        {errors.fieldName && (
          <p id="reviewworkspace-field-name-error" className="field-error text-sm text-error">
            {errors.fieldName.message}
          </p>
        )}
      </Field>
      <Field id="reviewworkspace-expected-value" label="Expected value">
        <input
          id="reviewworkspace-expected-value"
          className={
            "input input-sm w-full border-(--border-interactive) font-mono " + (errors.expected ? "input-error" : "")
          }
          {...register("expected")}
          aria-invalid={!!errors.expected}
          aria-describedby={errors.expected ? "reviewworkspace-expected-error" : undefined}
        />
        {errors.expected && (
          <p id="reviewworkspace-expected-error" className="field-error text-sm text-error">
            {errors.expected.message}
          </p>
        )}
      </Field>
      {selection.value.mode === "cells" && (
        <Field id="reviewworkspace-cell-range" label="Cell range" required>
          <input
            id="reviewworkspace-cell-range"
            className={
              "input input-sm w-full border-(--border-interactive) font-mono " + (selectionError ? "input-error" : "")
            }
            value={selection.value.cellRange}
            onChange={(event) => {
              selection.setCellRange(event.target.value);
              clearErrors("root.selection");
            }}
            placeholder="B3 or B3:C3"
            required
            aria-invalid={!!selectionError}
            aria-describedby={selectionError ? "reviewworkspace-cell-range-error" : undefined}
          />
          {selectionError && (
            <p id="reviewworkspace-cell-range-error" className="field-error text-sm text-error">
              {selectionError}
            </p>
          )}
        </Field>
      )}
      {selection.value.mode === "pdfjs" && (
        <p className="text-sm">
          {selection.value.pdfText ? (
            <>
              Selection on page {selection.value.pdfText.unit + 1}:{" "}
              <span className="font-mono">{selection.value.pdfText.text.slice(0, 80)}</span> (
              {selection.value.pdfText.rects.length} rect{selection.value.pdfText.rects.length === 1 ? "" : "s"})
            </>
          ) : (
            "No selection yet."
          )}
        </p>
      )}
      {selection.value.mode === "word_ids" && (
        <p className="text-sm">{selection.value.wordIds.length} word box(es) picked.</p>
      )}
      {selection.value.mode !== "cells" && selectionError && (
        <p className="field-error text-sm text-error" role="alert">
          {selectionError}
        </p>
      )}
      <Field id="reviewworkspace-notes" label="Notes">
        <input
          id="reviewworkspace-notes"
          className={"input input-sm w-full border-(--border-interactive) " + (errors.notes ? "input-error" : "")}
          {...register("notes")}
          aria-invalid={!!errors.notes}
          aria-describedby={errors.notes ? "reviewworkspace-notes-error" : undefined}
        />
        {errors.notes && (
          <p id="reviewworkspace-notes-error" className="field-error text-sm text-error">
            {errors.notes.message}
          </p>
        )}
      </Field>
      <div className="flex flex-wrap gap-2">
        <AsyncButton
          type="submit"
          className="btn btn-primary btn-sm"
          pending={createLabel.isPending && createLabel.variables?.request.mode !== "absent"}
          pendingLabel="Saving…"
          disabled={createLabel.isPending || disabled}
        >
          Save label
        </AsyncButton>
        <AsyncButton
          className="btn btn-outline btn-sm"
          pending={createLabel.isPending && createLabel.variables?.request.mode === "absent"}
          pendingLabel="Saving…"
          disabled={createLabel.isPending}
          onClick={() => void handleSubmit((values) => submit(values, "absent"))()}
        >
          Mark absent
        </AsyncButton>
      </div>
      <h3 className="mt-4">Labels on this document</h3>
      <ul className="space-y-1 text-sm">
        {labels.map((label) => (
          <li
            key={label.id}
            className="flex items-center justify-between gap-2 rounded border border-base-300 px-2 py-1"
          >
            <span>
              <strong>{label.field_name || label.category}</strong>{" "}
              {label.is_absent ? <em>absent</em> : <span className="font-mono">{label.expected_value}</span>}
            </span>
            <span className="text-caption text-secondary">
              v{label.version} · {label.mapping_method}
              {label.match_score != null ? " " + Math.round(label.match_score * 100) + "%" : ""} ·{" "}
              <StatusChip status={label.status === "final" ? "accepted" : label.status} />
            </span>
          </li>
        ))}
      </ul>
    </form>
  );
}
