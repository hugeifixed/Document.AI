import { useCallback, useMemo, useState } from "react";

type EvidenceMode = "pdfjs" | "word_ids" | "cells";
type SelectionErrorField = "selection" | "cellRange";

type SelectionRect = { x: number; y: number; width: number; height: number };

type PdfTextSelection = {
  unit: number;
  text: string;
  rects: SelectionRect[];
  pageWidth: number;
  pageHeight: number;
};

export type GroundTruthLabelRequest =
  | {
      document: string;
      mode: "pdfjs";
      field_name: string;
      expected_value: string;
      notes: string;
      unit_index: number;
      text: string;
      rects: SelectionRect[];
      page_width_pt: number;
      page_height_pt: number;
    }
  | {
      document: string;
      mode: "word_ids";
      field_name: string;
      expected_value: string;
      notes: string;
      unit_index: number;
      word_ids: string[];
    }
  | {
      document: string;
      mode: "cells";
      field_name: string;
      expected_value: string;
      notes: string;
      unit_index: number;
      cell_range: string;
    }
  | {
      document: string;
      mode: "absent";
      field_name: string;
      notes: string;
    };

type SelectionError = { field: SelectionErrorField; message: string };
type PreparedLabel = { ok: true; request: GroundTruthLabelRequest } | { ok: false; error: SelectionError };

type PdfTextCapture = {
  text: string;
  page: { left: number; top: number; width: number };
  rects: Array<{ left: number; bottom: number; width: number; height: number }>;
  pageWidth: number;
  pageHeight: number;
};

type LabelDraft = { fieldName: string; expectedValue: string; notes: string };

type SelectionState = {
  scope: string;
  mode: EvidenceMode;
  pdfText: PdfTextSelection | null;
  wordIds: string[];
  cellRange: string;
  error: SelectionError | null;
};

export type GroundTruthSelectionController = {
  value: Omit<SelectionState, "scope">;
  capturePdfText: (capture: PdfTextCapture) => PdfTextSelection | null;
  toggleWord: (wordId: string) => void;
  setCellRange: (cellRange: string) => void;
  prepareLabel: (draft: LabelDraft, intent?: "save" | "absent") => PreparedLabel;
  reset: () => void;
};

function evidenceMode(fileFormat: string | undefined, hasTextLayer: boolean | undefined): EvidenceMode {
  if (fileFormat === "xlsx" || fileFormat === "xls") return "cells";
  if (hasTextLayer === false) return "word_ids";
  return "pdfjs";
}

function emptySelection(scope: string, mode: EvidenceMode): SelectionState {
  return { scope, mode, pdfText: null, wordIds: [], cellRange: "", error: null };
}

export function useGroundTruthSelection({
  documentId,
  unit,
  fileFormat,
  hasTextLayer,
}: {
  documentId: string;
  unit: number;
  fileFormat?: string;
  hasTextLayer?: boolean;
}): GroundTruthSelectionController {
  const mode = evidenceMode(fileFormat, hasTextLayer);
  const scope = `${documentId}:${unit}:${mode}`;
  const [stored, setStored] = useState<SelectionState>(() => emptySelection(scope, mode));
  const current = stored.scope === scope ? stored : emptySelection(scope, mode);

  const update = useCallback(
    (change: (selection: SelectionState) => SelectionState) => {
      setStored((previous) => change(previous.scope === scope ? previous : emptySelection(scope, mode)));
    },
    [mode, scope],
  );

  const capturePdfText = useCallback(
    (capture: PdfTextCapture) => {
      if (mode !== "pdfjs" || capture.page.width <= 0 || capture.pageWidth <= 0 || capture.pageHeight <= 0) return null;
      const ratio = capture.pageWidth / capture.page.width;
      const rects = capture.rects
        .filter((rect) => rect.width > 1 && rect.height > 1)
        .map((rect) => ({
          x: (rect.left - capture.page.left) * ratio,
          y: capture.pageHeight - (rect.bottom - capture.page.top) * ratio,
          width: rect.width * ratio,
          height: rect.height * ratio,
        }));
      if (rects.length === 0) return null;
      const selection: PdfTextSelection = {
        unit,
        text: capture.text.replace(/\s+/g, " ").trim(),
        rects,
        pageWidth: capture.pageWidth,
        pageHeight: capture.pageHeight,
      };
      update((state) => ({ ...state, pdfText: selection, error: null }));
      return selection;
    },
    [mode, unit, update],
  );

  const toggleWord = useCallback(
    (wordId: string) => {
      if (mode !== "word_ids") return;
      update((state) => ({
        ...state,
        wordIds: state.wordIds.includes(wordId)
          ? state.wordIds.filter((candidate) => candidate !== wordId)
          : [...state.wordIds, wordId],
        error: null,
      }));
    },
    [mode, update],
  );

  const setCellRange = useCallback(
    (cellRange: string) => {
      if (mode !== "cells") return;
      update((state) => ({ ...state, cellRange: cellRange.toUpperCase(), error: null }));
    },
    [mode, update],
  );

  const prepareLabel = useCallback(
    (draft: LabelDraft, intent: "save" | "absent" = "save"): PreparedLabel => {
      const base = { document: documentId, field_name: draft.fieldName.trim(), notes: draft.notes };
      if (intent === "absent") {
        update((state) => ({ ...state, error: null }));
        return { ok: true, request: { ...base, mode: "absent" } };
      }
      if (current.mode === "cells") {
        if (!/^[A-Z]+[1-9]\d*(?::[A-Z]+[1-9]\d*)?$/.test(current.cellRange)) {
          const error = { field: "cellRange" as const, message: "Enter a cell or range such as B3 or B3:C3." };
          update((state) => ({ ...state, error }));
          return { ok: false, error };
        }
        update((state) => ({ ...state, error: null }));
        return {
          ok: true,
          request: {
            ...base,
            mode: "cells",
            expected_value: draft.expectedValue,
            unit_index: unit,
            cell_range: current.cellRange,
          },
        };
      }
      if (current.mode === "word_ids") {
        if (current.wordIds.length === 0) {
          const error = { field: "selection" as const, message: "Pick at least one word box on the document." };
          update((state) => ({ ...state, error }));
          return { ok: false, error };
        }
        update((state) => ({ ...state, error: null }));
        return {
          ok: true,
          request: {
            ...base,
            mode: "word_ids",
            expected_value: draft.expectedValue,
            unit_index: unit,
            word_ids: current.wordIds,
          },
        };
      }
      if (!current.pdfText) {
        const error = { field: "selection" as const, message: "Select text on the page first." };
        update((state) => ({ ...state, error }));
        return { ok: false, error };
      }
      update((state) => ({ ...state, error: null }));
      return {
        ok: true,
        request: {
          ...base,
          mode: "pdfjs",
          expected_value: draft.expectedValue,
          unit_index: unit,
          text: current.pdfText.text,
          rects: current.pdfText.rects,
          page_width_pt: current.pdfText.pageWidth,
          page_height_pt: current.pdfText.pageHeight,
        },
      };
    },
    [current, documentId, unit, update],
  );

  const reset = useCallback(() => setStored(emptySelection(scope, mode)), [mode, scope]);
  const value = useMemo(
    () => ({
      mode: current.mode,
      pdfText: current.pdfText,
      wordIds: current.wordIds,
      cellRange: current.cellRange,
      error: current.error,
    }),
    [current.cellRange, current.error, current.mode, current.pdfText, current.wordIds],
  );

  return useMemo(
    () => ({ value, capturePdfText, toggleWord, setCellRange, prepareLabel, reset }),
    [capturePdfText, prepareLabel, reset, setCellRange, toggleWord, value],
  );
}
