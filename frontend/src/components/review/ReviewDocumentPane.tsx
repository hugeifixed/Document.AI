import { lazy, Suspense, useCallback, useEffect, useMemo, useRef } from "react";
import { announce } from "@/a11y/announce";
import type { Document, LayoutUnit, Run, Span } from "@/api/types";
import { ErrorNotice } from "@/components/ErrorNotice";
import { polygonBounds } from "@/components/review/geometry";

const LazyPdfViewer = lazy(() => import("@/components/PdfViewer").then((module) => ({ default: module.PdfViewer })));

type Rect = { x: number; y: number; width: number; height: number };
export interface DocumentSelection {
  unit: number;
  text: string;
  rects: Rect[];
  pageW: number;
  pageH: number;
}

function Overlay({ polygon, selected, label }: { polygon: number[]; selected?: boolean; label: string }) {
  const bounds = polygonBounds(polygon);
  if (!bounds) return null;
  return (
    <div className={"overlay-box " + (selected ? "selected" : "")} style={bounds} aria-hidden="true" title={label} />
  );
}

function WordButton({
  id,
  text,
  polygon,
  picked,
  onToggle,
}: {
  id: string;
  text: string;
  polygon: number[];
  picked: boolean;
  onToggle: (id: string) => void;
}) {
  const bounds = polygonBounds(polygon);
  if (!bounds) return null;
  return (
    <button
      type="button"
      className={"overlay-word pointer-events-auto " + (picked ? "picked" : "")}
      aria-pressed={picked}
      aria-label={"word " + text}
      style={bounds}
      onClick={() => onToggle(id)}
    />
  );
}

export function ReviewDocumentPane({
  mode,
  document,
  unit,
  onUnitChange,
  scale,
  onScaleChange,
  activeRun,
  runs,
  onRunChange,
  layout,
  layoutError,
  onRetryLayout,
  spans,
  selectedField,
  picked,
  onToggleWord,
  cellRange,
  onCellRangeChange,
  onSelection,
}: {
  mode: "review" | "label";
  document: Document;
  unit: number;
  onUnitChange: (unit: number) => void;
  scale: number;
  onScaleChange: (scale: number) => void;
  activeRun?: string | null;
  runs: Run[];
  onRunChange: (run: string) => void;
  layout?: LayoutUnit;
  layoutError: boolean;
  onRetryLayout: () => void;
  spans: Span[];
  selectedField: string | null;
  picked: string[];
  onToggleWord: (id: string) => void;
  cellRange: string;
  onCellRangeChange: (range: string) => void;
  onSelection: (selection: DocumentSelection) => void;
}) {
  const pageRef = useRef<HTMLDivElement>(null);
  const units = document.units ?? [];
  const isSheet = document.file_format === "xlsx" || document.file_format === "xls";
  const isPdf = document.file_format === "pdf";
  const isImage = ["png", "jpeg", "tiff"].includes(document.file_format);
  const cellsByPosition = useMemo(
    () => new Map((layout?.cells ?? []).map((cell) => [cell.row + ":" + cell.col, cell])),
    [layout?.cells],
  );
  const highlightedWordIds = useMemo(() => new Set(spans.flatMap((span) => span.word_ids)), [spans]);

  const captureSelection = useCallback(() => {
    if (mode !== "label" || !isPdf || !layout?.width || !layout.height) return;
    const selection = window.getSelection();
    const pageElement = pageRef.current?.querySelector(".react-pdf__Page");
    if (!selection || selection.isCollapsed || !pageElement || !pageElement.contains(selection.anchorNode)) return;
    const page = pageElement.getBoundingClientRect();
    const range = selection.getRangeAt(0);
    const ratio = layout.width / page.width;
    const rects: Rect[] = Array.from(range.getClientRects())
      .filter((rect) => rect.width > 1 && rect.height > 1)
      .map((rect) => ({
        x: (rect.left - page.left) * ratio,
        y: layout.height! - (rect.bottom - page.top) * ratio,
        width: rect.width * ratio,
        height: rect.height * ratio,
      }));
    if (!rects.length) return;
    const text = selection.toString().replace(/\s+/g, " ").trim();
    onSelection({ unit, text, rects, pageW: layout.width, pageH: layout.height });
    announce('Selected "' + text.slice(0, 60) + '"');
  }, [isPdf, layout, mode, onSelection, unit]);

  useEffect(() => {
    globalThis.document.addEventListener("mouseup", captureSelection);
    globalThis.document.addEventListener("keyup", captureSelection);
    return () => {
      globalThis.document.removeEventListener("mouseup", captureSelection);
      globalThis.document.removeEventListener("keyup", captureSelection);
    };
  }, [captureSelection]);

  const fileUrl = "/api/v1/documents/" + document.id + "/original/";
  return (
    <section aria-label="Document" className="min-w-0 rounded-box border border-base-300 bg-base-100 p-4 sm:p-5">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        <h1 className="min-w-0 [overflow-wrap:anywhere] text-section-title">{document.original_filename}</h1>
        <label className="ml-auto flex min-w-0 max-w-full flex-wrap items-center gap-1">
          {isSheet ? "Sheet" : "Page"}
          <select
            className="select border-(--border-interactive) select-xs"
            value={unit}
            onChange={(event) => onUnitChange(Number(event.target.value))}
          >
            {units.map((sourceUnit) => (
              <option key={sourceUnit.id} value={sourceUnit.index}>
                {sourceUnit.label}
              </option>
            ))}
          </select>
        </label>
        {!isSheet && (
          <>
            <button
              type="button"
              className="btn btn-xs btn-outline"
              onClick={() => onScaleChange(Math.max(0.5, scale - 0.2))}
              aria-label="Zoom out"
            >
              −
            </button>
            <span className="tabular-nums">{Math.round(scale * 100)}%</span>
            <button
              type="button"
              className="btn btn-xs btn-outline"
              onClick={() => onScaleChange(Math.min(3, scale + 0.2))}
              aria-label="Zoom in"
            >
              +
            </button>
          </>
        )}
        {activeRun && (
          <label className="flex min-w-0 max-w-full flex-wrap items-center gap-1">
            Run
            <select
              className="select border-(--border-interactive) select-xs"
              value={activeRun}
              onChange={(event) => onRunChange(event.target.value)}
            >
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.name || run.workflow_name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {layoutError && (
        <div className="mb-3">
          <ErrorNotice message="This page layout could not be loaded." onRetry={onRetryLayout} />
        </div>
      )}
      {mode === "label" && isPdf && layout?.has_text_layer !== false && (
        <p className="mb-2 text-sm text-secondary">
          Select text on the page with the mouse or keyboard (Shift+arrows in the text layer), then fill in the field on
          the right.
        </p>
      )}
      {mode === "label" && layout?.has_text_layer === false && (
        <p className="mb-2 text-sm text-secondary">
          This page has no text layer: click word boxes to build the selection.
        </p>
      )}
      <div ref={pageRef} className="relative inline-block max-w-full overflow-auto">
        {isPdf && (
          <Suspense fallback={<output className="block">Loading PDF viewer…</output>}>
            <LazyPdfViewer file={fileUrl} pageNumber={unit + 1} scale={scale}>
              {spans.map((span) => (
                <Overlay
                  key={span.id + span.text}
                  polygon={span.polygon}
                  selected={span.id === selectedField}
                  label={span.text}
                />
              ))}
              {layout?.has_text_layer === false &&
                layout.words?.map((word) => (
                  <WordButton
                    key={word.id}
                    id={word.id}
                    text={word.text}
                    polygon={word.polygon}
                    picked={picked.includes(word.id)}
                    onToggle={onToggleWord}
                  />
                ))}
            </LazyPdfViewer>
          </Suspense>
        )}
        {isImage && (
          <div className="relative">
            <img
              src={fileUrl}
              alt={document.original_filename + ", page " + (unit + 1)}
              style={{ width: scale * 700 + "px" }}
            />
            <div className="pointer-events-none absolute inset-0">
              {spans.map((span) => (
                <Overlay key={span.id} polygon={span.polygon} selected={span.id === selectedField} label={span.text} />
              ))}
              {mode === "label" &&
                layout?.words?.map((word) => (
                  <WordButton
                    key={word.id}
                    id={word.id}
                    text={word.text}
                    polygon={word.polygon}
                    picked={picked.includes(word.id)}
                    onToggle={onToggleWord}
                  />
                ))}
            </div>
          </div>
        )}
        {isSheet && layout?.cells && (
          <div className="overflow-auto">
            <table className="table table-xs font-mono">
              <caption className="sr-only">Sheet {layout.name}</caption>
              <tbody>
                {Array.from({ length: layout.row_count ?? 0 }).map((_, row) => (
                  <tr key={row}>
                    <th scope="row">{row + 1}</th>
                    {Array.from({ length: layout.col_count ?? 0 }).map((__, column) => {
                      const cell = cellsByPosition.get(row + ":" + column);
                      const highlighted = !!cell && highlightedWordIds.has(cell.id);
                      return (
                        <td
                          key={column}
                          className={
                            (highlighted ? "bg-info/20 " : "") + (cellRange === cell?.ref ? "ring-2 ring-primary" : "")
                          }
                          title={cell?.formula ?? undefined}
                        >
                          {mode === "label" && cell ? (
                            <button
                              type="button"
                              className="w-full text-left"
                              onClick={() => onCellRangeChange(cell.ref)}
                              aria-label={"cell " + cell.ref + " " + (cell.value ?? "")}
                            >
                              {cell.value}
                            </button>
                          ) : (
                            cell?.value
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!isPdf && !isImage && !isSheet && (
          <pre className="font-mono max-h-[70vh] overflow-auto whitespace-pre-wrap p-2 text-sm">{layout?.content}</pre>
        )}
      </div>
    </section>
  );
}
