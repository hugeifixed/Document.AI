import { act, renderHook } from "@testing-library/react";
import { useGroundTruthSelection } from "@/groundTruth/selection";

const draft = { fieldName: " account_number ", expectedValue: "1234", notes: "Verified" };

describe("GroundTruthLabel selection", () => {
  it("normalizes PDF text geometry and prepares its complete label request", () => {
    const { result } = renderHook(() =>
      useGroundTruthSelection({
        documentId: "document-1",
        unit: 1,
        fileFormat: "pdf",
        hasTextLayer: true,
      }),
    );

    act(() => {
      result.current.capturePdfText({
        text: "  Account\n  1234 ",
        page: { left: 10, top: 20, width: 100 },
        rects: [
          { left: 20, bottom: 50, width: 20, height: 10 },
          { left: 0, bottom: 0, width: 1, height: 1 },
        ],
        pageWidth: 200,
        pageHeight: 400,
      });
    });

    expect(result.current.value.pdfText).toEqual({
      unit: 1,
      text: "Account 1234",
      rects: [{ x: 20, y: 340, width: 40, height: 20 }],
      pageWidth: 200,
      pageHeight: 400,
    });
    expect(result.current.prepareLabel(draft)).toEqual({
      ok: true,
      request: {
        document: "document-1",
        mode: "pdfjs",
        field_name: "account_number",
        expected_value: "1234",
        notes: "Verified",
        unit_index: 1,
        text: "Account 1234",
        rects: [{ x: 20, y: 340, width: 40, height: 20 }],
        page_width_pt: 200,
        page_height_pt: 400,
      },
    });
  });

  it("requires layout words and preserves their selection order", () => {
    const { result } = renderHook(() =>
      useGroundTruthSelection({
        documentId: "document-1",
        unit: 0,
        fileFormat: "pdf",
        hasTextLayer: false,
      }),
    );

    let missing: ReturnType<typeof result.current.prepareLabel>;
    act(() => {
      missing = result.current.prepareLabel(draft);
    });
    expect(missing!).toEqual({
      ok: false,
      error: { field: "selection", message: "Pick at least one word box on the document." },
    });

    act(() => {
      result.current.toggleWord("p1:w1");
      result.current.toggleWord("p1:w2");
    });
    expect(result.current.value.wordIds).toEqual(["p1:w1", "p1:w2"]);
    expect(result.current.prepareLabel(draft)).toMatchObject({
      ok: true,
      request: { mode: "word_ids", unit_index: 0, word_ids: ["p1:w1", "p1:w2"] },
    });
  });

  it("normalizes and validates spreadsheet cell ranges", () => {
    const { result } = renderHook(() =>
      useGroundTruthSelection({ documentId: "sheet-1", unit: 2, fileFormat: "xlsx" }),
    );

    let missing: ReturnType<typeof result.current.prepareLabel>;
    act(() => {
      missing = result.current.prepareLabel(draft);
    });
    expect(missing!).toEqual({
      ok: false,
      error: { field: "cellRange", message: "Enter a cell or range such as B3 or B3:C3." },
    });

    act(() => result.current.setCellRange("b3:c3"));
    expect(result.current.prepareLabel(draft)).toMatchObject({
      ok: true,
      request: { document: "sheet-1", mode: "cells", unit_index: 2, cell_range: "B3:C3" },
    });
  });

  it("prepares explicit absence without source evidence", () => {
    const { result } = renderHook(() =>
      useGroundTruthSelection({ documentId: "document-1", unit: 0, fileFormat: "pdf" }),
    );

    expect(result.current.prepareLabel(draft, "absent")).toEqual({
      ok: true,
      request: {
        document: "document-1",
        mode: "absent",
        field_name: "account_number",
        notes: "Verified",
      },
    });
  });

  it("resets evidence immediately when the document unit changes", () => {
    let unit = 0;
    const { result, rerender } = renderHook(() =>
      useGroundTruthSelection({
        documentId: "document-1",
        unit,
        fileFormat: "png",
        hasTextLayer: false,
      }),
    );

    act(() => result.current.toggleWord("p1:w1"));
    expect(result.current.value.wordIds).toEqual(["p1:w1"]);

    unit = 1;
    rerender();
    expect(result.current.value.wordIds).toEqual([]);
    expect(result.current.value.error).toBeNull();
  });
});
