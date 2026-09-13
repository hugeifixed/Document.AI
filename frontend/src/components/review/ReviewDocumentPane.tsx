import { lazy, Suspense, useCallback, useEffect, useId, useMemo, useRef } from "react";
import { announce } from "@/a11y/announce";
import type { Document, LayoutUnit, Run, Span } from "@/api/types";
import { ErrorNotice } from "@/components/ErrorNotice";
import { SelectControl, StatusChip } from "@/components/ui";
import type { GroundTruthSelectionController } from "@/groundTruth/selection";

const LazyPdfViewer = lazy(() => import("@/components/PdfViewer").then((module) => ({ default: module.PdfViewer })));

function polygonBounds(polygon: number[]) {
  if (polygon.length < 8) return null;
  const xs = polygon.filter((_, index) => index % 2 === 0);
  const ys = polygon.filter((_, index) => index % 2 === 1);
  const left = Math.min(...xs);
  const top = Math.min(...ys);
  return {
    left: `${left * 100}%`,
    top: `${top * 100}%`,
    width: `${(Math.max(...xs) - left) * 100}%`,
    height: `${(Math.max(...ys) - top) * 100}%`,
  };
}

function Overlay({ polygon, selected, label }: { polygon: number[]; selected?: boolean; label: string }) {
  const bounds = polygonBounds(polygon);
  if (!bounds) return null;
  return (
    <div className={"overlay-box " + (selected ? "selected" : "")} style={bounds} aria-hidden="true" title={label} />
  );
}

function runOptionLabel(run: Run) {
  const name = run.name ? `${run.name} · ` : "";
  const date = new Date(run.created).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
  return `${name}${run.workflow_name} v${run.workflow_version} · ${date} · ${run.status}`;
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
  groundTruth,
  viewingOriginal = false,
  onSourceChange,
}: {
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
  groundTruth?: GroundTruthSelectionController;
  viewingOriginal?: boolean;
  onSourceChange?: (original: boolean) => void;
}) {
  const pageRef = useRef<HTMLDivElement>(null);
  const resultVersionId = useId();
  const resultVersionHelpId = `${resultVersionId}-help`;
  const units = document.units ?? [];
  const fileFormat = viewingOriginal
    ? document.file_format
    : (document.processing_source?.file_format ?? document.file_format);
  const isSheet = fileFormat === "xlsx" || fileFormat === "xls";
  const isPdf = fileFormat === "pdf";
  const isImage = ["png", "jpg", "jpeg"].includes(fileFormat);
  const selectedRun = runs.find((run) => run.id === activeRun);
  const cellsByPosition = useMemo(
    () => new Map((layout?.cells ?? []).map((cell) => [cell.row + ":" + cell.col, cell])),
    [layout?.cells],
  );
  const highlightedWordIds = useMemo(() => new Set(spans.flatMap((span) => span.word_ids)), [spans]);
  const groundTruthMode = groundTruth?.value.mode;
  const captureGroundTruthPdfText = groundTruth?.capturePdfText;

  const captureSelection = useCallback(() => {
    if (groundTruthMode !== "pdfjs" || !captureGroundTruthPdfText || !isPdf || !layout?.width || !layout.height) return;
    const selection = window.getSelection();
    const pageElement = pageRef.current?.querySelector(".react-pdf__Page");
    if (!selection || selection.isCollapsed || !pageElement || !pageElement.contains(selection.anchorNode)) return;
    const page = pageElement.getBoundingClientRect();
    const range = selection.getRangeAt(0);
    const captured = captureGroundTruthPdfText({
      text: selection.toString(),
      page: { left: page.left, top: page.top, width: page.width },
      rects: Array.from(range.getClientRects()).map((rect) => ({
        left: rect.left,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
      })),
      pageWidth: layout.width,
      pageHeight: layout.height,
    });
    if (captured) announce('Selected "' + captured.text.slice(0, 60) + '"');
  }, [captureGroundTruthPdfText, groundTruthMode, isPdf, layout]);

  useEffect(() => {
    globalThis.document.addEventListener("mouseup", captureSelection);
    globalThis.document.addEventListener("keyup", captureSelection);
    return () => {
      globalThis.document.removeEventListener("mouseup", captureSelection);
      globalThis.document.removeEventListener("keyup", captureSelection);
    };
  }, [captureSelection]);

  const originalUrl = "/api/v1/documents/" + document.id + "/original/";
  const fileUrl = viewingOriginal ? originalUrl : (document.processing_source?.url ?? originalUrl);
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
        {selectedRun && runs.length > 1 && (
          <div className="grid min-w-0 max-w-full gap-1">
            <label htmlFor={resultVersionId} className="font-medium">
              Result version
            </label>
            <SelectControl
              id={resultVersionId}
              className="border-(--border-interactive) select-xs min-w-64 max-w-full"
              value={activeRun ?? ""}
              aria-describedby={resultVersionHelpId}
              onChange={(event) => onRunChange(event.target.value)}
            >
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {runOptionLabel(run)}
                </option>
              ))}
            </SelectControl>
            <span id={resultVersionHelpId} className="text-caption">
              Switch to view this document&apos;s output from another run.
            </span>
          </div>
        )}
        {selectedRun && runs.length === 1 && (
          <div aria-label="Processing provenance" className="flex min-w-0 max-w-full flex-wrap items-center gap-1.5">
            <span className="text-secondary">Processed in</span>
            {selectedRun.name && (
              <span className="max-w-48 truncate font-medium" title={selectedRun.name}>
                {selectedRun.name}
              </span>
            )}
            <span className="text-secondary">
              {selectedRun.name && <span aria-hidden="true">· </span>}
              {selectedRun.workflow_name} v{selectedRun.workflow_version}
            </span>
            <StatusChip status={selectedRun.status} />
          </div>
        )}
      </div>
      {document.processing_source?.is_original === false && onSourceChange && (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-secondary">
            {viewingOriginal
              ? "Original upload · highlights and labeling are hidden"
              : "Processing source · highlights match this result version"}
          </span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => onSourceChange(!viewingOriginal)}>
            {viewingOriginal ? "View processing source" : "View original"}
          </button>
        </div>
      )}
      {layoutError && (
        <div className="mb-3">
          <ErrorNotice message="This page layout could not be loaded." onRetry={onRetryLayout} />
        </div>
      )}
      {groundTruth?.value.mode === "pdfjs" && isPdf && (
        <p className="mb-2 text-sm text-secondary">
          Select text on the page with the mouse or keyboard (Shift+arrows in the text layer), then fill in the field on
          the right.
        </p>
      )}
      {groundTruth?.value.mode === "word_ids" && (
        <p className="mb-2 text-sm text-secondary">
          This page has no text layer: click word boxes to build the selection.
        </p>
      )}
      <div ref={pageRef} className="relative inline-block max-w-full overflow-auto">
        {isPdf && (
          <Suspense fallback={<output className="block">Loading PDF viewer…</output>}>
            <LazyPdfViewer
              key={fileUrl}
              file={fileUrl}
              pageNumber={unit + 1}
              scale={scale}
              renderTextLayer={viewingOriginal || layout?.has_text_layer !== false}
            >
              {spans.map((span) => (
                <Overlay
                  key={span.id + span.text}
                  polygon={span.polygon}
                  selected={span.id === selectedField}
                  label={span.text}
                />
              ))}
              {groundTruth?.value.mode === "word_ids" &&
                layout?.words?.map((word) => (
                  <WordButton
                    key={word.id}
                    id={word.id}
                    text={word.text}
                    polygon={word.polygon}
                    picked={groundTruth.value.wordIds.includes(word.id)}
                    onToggle={groundTruth.toggleWord}
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
              {groundTruth?.value.mode === "word_ids" &&
                layout?.words?.map((word) => (
                  <WordButton
                    key={word.id}
                    id={word.id}
                    text={word.text}
                    polygon={word.polygon}
                    picked={groundTruth.value.wordIds.includes(word.id)}
                    onToggle={groundTruth.toggleWord}
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
                            (highlighted ? "bg-info/20 " : "") +
                            (groundTruth?.value.cellRange === cell?.ref ? "ring-2 ring-primary" : "")
                          }
                          title={cell?.formula ?? undefined}
                        >
                          {groundTruth?.value.mode === "cells" && cell ? (
                            <button
                              type="button"
                              className="w-full text-left"
                              onClick={() => groundTruth.setCellRange(cell.ref)}
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
        {fileFormat === "tiff" && (
          <p className="text-sm text-secondary">
            This browser cannot preview the original TIFF.{" "}
            <a className="link link-primary" href={originalUrl}>
              Download original TIFF
            </a>
          </p>
        )}
        {!isPdf && !isImage && !isSheet && fileFormat !== "tiff" && (
          <pre className="font-mono max-h-[70vh] overflow-auto whitespace-pre-wrap p-2 text-sm">{layout?.content}</pre>
        )}
      </div>
    </section>
  );
}
