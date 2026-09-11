import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiError, apiFieldError, errorMessage, post } from "@/api/client";
import type { Label, LayoutUnit } from "@/api/types";
import type { DocumentSelection } from "@/components/review/ReviewDocumentPane";
import { AsyncButton, Field, StatusChip } from "@/components/ui";

const labelSchema = z.object({
  fieldName: z.string().refine((value) => value.trim().length > 0, "Enter a field name."),
  expected: z.string(),
  cellRange: z.string(),
  notes: z.string(),
});
type LabelForm = z.infer<typeof labelSchema>;

export function LabelPanel({
  documentId,
  unit,
  isSheet,
  layout,
  selection,
  picked,
  cellRange,
  onCellRangeChange,
  schemaFields,
  labels,
  onSaved,
}: {
  documentId: string;
  unit: number;
  isSheet: boolean;
  layout?: LayoutUnit;
  selection: DocumentSelection | null;
  picked: string[];
  cellRange: string;
  onCellRangeChange: (range: string) => void;
  schemaFields: string[];
  labels: Label[];
  onSaved: () => void;
}) {
  const qc = useQueryClient();
  const {
    register,
    handleSubmit,
    setError,
    setValue,
    clearErrors,
    formState: { errors },
  } = useForm<LabelForm>({
    resolver: zodResolver(labelSchema),
    defaultValues: { fieldName: "", expected: "", cellRange: "", notes: "" },
  });

  useEffect(() => {
    if (selection) setValue("expected", selection.text, { shouldDirty: true });
  }, [selection, setValue]);
  useEffect(() => {
    setValue("cellRange", cellRange, { shouldValidate: false });
  }, [cellRange, setValue]);

  const applyServerErrors = (error: unknown) => {
    for (const [serverName, formName] of [
      ["field_name", "fieldName"],
      ["expected_value", "expected"],
      ["cell_range", "cellRange"],
      ["notes", "notes"],
    ] as const) {
      const message = apiFieldError(error, serverName);
      if (message) setError(formName, { type: "server", message });
    }
    toast.error(errorMessage(error));
  };

  const createLabel = useMutation({
    mutationFn: (values: LabelForm) => {
      clearErrors("root");
      const base = {
        document: documentId,
        field_name: values.fieldName.trim(),
        expected_value: values.expected,
        notes: values.notes,
        unit_index: unit,
      };
      if (isSheet) {
        if (!/^[A-Z]+[1-9]\d*(?::[A-Z]+[1-9]\d*)?$/.test(values.cellRange)) {
          setError("cellRange", { type: "validate", message: "Enter a cell or range such as B3 or B3:C3." });
          throw new ApiError(0, { message: "Enter a valid cell range." });
        }
        return post<Label>("/labels/", { ...base, mode: "cells", cell_range: values.cellRange });
      }
      if (layout?.has_text_layer === false) {
        if (!picked.length) {
          setError("root.selection", { type: "validate", message: "Pick at least one word box on the document." });
          throw new ApiError(0, { message: "Pick at least one word box on the document." });
        }
        return post<Label>("/labels/", { ...base, mode: "word_ids", word_ids: picked });
      }
      if (!selection) {
        setError("root.selection", { type: "validate", message: "Select text on the page first." });
        throw new ApiError(0, { message: "Select text on the page first." });
      }
      return post<Label>("/labels/", {
        ...base,
        mode: "pdfjs",
        text: selection.text,
        rects: selection.rects,
        page_width_pt: selection.pageW,
        page_height_pt: selection.pageH,
      });
    },
    onSuccess: (label) => {
      toast.success(
        "Label saved · " +
          label.mapping_method +
          " (" +
          (label.match_score != null ? Math.round(label.match_score * 100) + "%" : "n/a") +
          ")" +
          (label.mapping_exceptions.length ? " — " + label.mapping_exceptions[0] : ""),
      );
      setValue("expected", "");
      setValue("cellRange", "");
      onSaved();
      qc.invalidateQueries({ queryKey: ["labels", documentId] });
    },
    onError: applyServerErrors,
  });
  const markAbsent = useMutation({
    mutationFn: (values: LabelForm) =>
      post<Label>("/labels/", {
        document: documentId,
        mode: "absent",
        field_name: values.fieldName.trim(),
        notes: values.notes,
      }),
    onSuccess: () => {
      toast.success("Marked absent");
      setValue("expected", "");
      setValue("cellRange", "");
      onSaved();
      qc.invalidateQueries({ queryKey: ["labels", documentId] });
    },
    onError: applyServerErrors,
  });
  const { ref: cellRangeRef, onBlur: onCellRangeBlur, name: cellRangeName } = register("cellRange");

  return (
    <form className="space-y-4" onSubmit={handleSubmit((values) => createLabel.mutate(values))}>
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
      {isSheet && (
        <Field id="reviewworkspace-cell-range" label="Cell range" required>
          <input
            id="reviewworkspace-cell-range"
            className={
              "input input-sm w-full border-(--border-interactive) font-mono " + (errors.cellRange ? "input-error" : "")
            }
            ref={cellRangeRef}
            name={cellRangeName}
            onBlur={onCellRangeBlur}
            value={cellRange}
            onChange={(event) => {
              const value = event.target.value.toUpperCase();
              setValue("cellRange", value, { shouldDirty: true, shouldValidate: !!errors.cellRange });
              onCellRangeChange(value);
            }}
            placeholder="B3 or B3:C3"
            required
            aria-invalid={!!errors.cellRange}
            aria-describedby={errors.cellRange ? "reviewworkspace-cell-range-error" : undefined}
          />
          {errors.cellRange && (
            <p id="reviewworkspace-cell-range-error" className="field-error text-sm text-error">
              {errors.cellRange.message}
            </p>
          )}
        </Field>
      )}
      {!isSheet && layout?.has_text_layer !== false && (
        <p className="text-sm">
          {selection ? (
            <>
              Selection on page {selection.unit + 1}: <span className="font-mono">{selection.text.slice(0, 80)}</span> (
              {selection.rects.length} rect{selection.rects.length === 1 ? "" : "s"})
            </>
          ) : (
            "No selection yet."
          )}
        </p>
      )}
      {layout?.has_text_layer === false && <p className="text-sm">{picked.length} word box(es) picked.</p>}
      {errors.root?.selection?.message && (
        <p className="field-error text-sm text-error" role="alert">
          {errors.root.selection.message}
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
          pending={createLabel.isPending}
          pendingLabel="Saving…"
          disabled={markAbsent.isPending}
        >
          Save label
        </AsyncButton>
        <AsyncButton
          className="btn btn-outline btn-sm"
          pending={markAbsent.isPending}
          pendingLabel="Saving…"
          disabled={createLabel.isPending}
          onClick={() => void handleSubmit((values) => markAbsent.mutate(values))()}
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
