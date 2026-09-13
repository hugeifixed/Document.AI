import { lazy, type Ref, Suspense, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { announce } from "@/a11y/announce";
import type { Document, LayoutUnit, Run, Span } from "@/api/types";
import { ErrorNotice } from "@/components/ErrorNotice";
import { ScrollRegion, SelectControl, StatusChip } from "@/components/ui";
import type { GroundTruthSelectionController } from "@/groundTruth/selection";
import { type EvidenceRequest, polygonBounds } from "./evidence";

const LazyPdfViewer = lazy(() => import("@/components/PdfViewer").then((module) => ({ default: module.PdfViewer })));

function Overlay({
  polygon,
  selected,
  label,
  elementRef,
  emphasized,
  onEmphasisEnd,
}: {
  polygon: number[];
  selected?: boolean;
  label: string;
  elementRef?: Ref<HTMLDivElement>;
  emphasized?: boolean;
  onEmphasisEnd?: () => void;
}) {
  const bounds = polygonBounds(polygon);
  if (!bounds) return null;
  return (
    <div
      ref={elementRef}
      className={"overlay-box " + (selected ? "selected " : "") + (emphasized ? "evidence-emphasis" : "")}
      style={bounds}
      aria-hidden="true"
      title={label}
      onAnimationEnd={onEmphasisEnd}
    />
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
  evidenceRequest,
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
  evidenceRequest?: EvidenceRequest | null;
}) {
  const pageRef = useRef<HTMLDivElement>(null);
  const evidenceRef = useRef<HTMLDivElement>(null);
  const handledEvidence = useRef<number | null>(null);
  const [renderState, setRenderState] = useState({ key: "", generation: 0, ready: false });
  const [located, setLocated] = useState<{ id: number; message: string } | null>(null);
  const [emphasizedRequest, setEmphasizedRequest] = useState<number | null>(null);
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
  const renderKey = JSON.stringify([fileUrl, document.processing_source?.layout_artifact, unit, scale]);
  // Invalidate before committing the new page, including a return to a previously
  // rendered page while another render is still pending.
  if (renderState.key !== renderKey) {
    setRenderState({ key: renderKey, generation: renderState.generation + 1, ready: false });
    setEmphasizedRequest(null);
  }
  const renderGeneration = renderState.generation;
  const onPageRendered = useCallback(() => {
    setRenderState((current) =>
      current.key === renderKey && current.generation === renderGeneration ? { ...current, ready: true } : current,
    );
  }, [renderGeneration, renderKey]);
  const pageReady = isPdf || isImage ? renderState.key === renderKey && renderState.ready : layout?.index === unit;
  const targetIndex = spans.findIndex((span) => span.id === selectedField && polygonBounds(span.polygon));

  useEffect(() => {
    if (!evidenceRequest || handledEvidence.current === evidenceRequest.id) return;
    if (viewingOriginal && evidenceRequest.unit !== null) return;
    if (evidenceRequest.unit !== null && (evidenceRequest.unit !== unit || !pageReady)) return;
    handledEvidence.current = evidenceRequest.id;
    const prefix = evidenceRequest.switchedSource ? "Showing evidence on the processing source. " : "";
    let message = `No evidence location is saved for ${evidenceRequest.fieldName}.`;
    if (evidenceRequest.unit !== null) {
      const location = `${isSheet ? "sheet" : "page"} ${unit + 1}`;
      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const target = evidenceRef.current;
      (target ?? pageRef.current)?.scrollIntoView({
        behavior: reducedMotion ? "instant" : "smooth",
        block: target ? "center" : "nearest",
        inline: target ? "center" : "nearest",
      });
      if (target && !reducedMotion) setEmphasizedRequest(evidenceRequest.id);
      message = `${evidenceRequest.fieldName}, ${location}.`;
      if ((isPdf || isImage) && !target) message += " No bounding box is saved for this field.";
    }
    const status = prefix + message;
    setLocated({ id: evidenceRequest.id, message: status });
    return announce(status);
  }, [evidenceRequest, isImage, isPdf, isSheet, pageReady, unit, viewingOriginal]);

  const overlays = spans.map((span, index) => (
    <Overlay
      key={`${span.id}:${index}:${index === targetIndex ? (evidenceRequest?.id ?? "") : ""}`}
      polygon={span.polygon}
      selected={span.id === selectedField}
      label={span.text}
      elementRef={index === targetIndex ? evidenceRef : undefined}
      emphasized={index === targetIndex && emphasizedRequest === evidenceRequest?.id}
      onEmphasisEnd={() => setEmphasizedRequest(null)}
    />
  ));
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
      {evidenceRequest && (
        <p className="mb-2 text-caption text-secondary" data-evidence-status="">
          {located?.id === evidenceRequest.id ? located.message : `Locating ${evidenceRequest.fieldName}…`}
        </p>
      )}
      <ScrollRegion label="Document preview" className="relative max-h-[70vh] w-full">
        <div ref={pageRef}>
          {isPdf && (
            <Suspense fallback={<output className="block">Loading PDF viewer…</output>}>
              <LazyPdfViewer
                key={`${fileUrl}:${document.processing_source?.layout_artifact ?? ""}`}
                file={fileUrl}
                pageNumber={unit + 1}
                scale={scale}
                renderTextLayer={viewingOriginal || layout?.has_text_layer !== false}
                onPageRendered={onPageRendered}
              >
                {overlays}
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
            <div key={renderKey} className="relative w-max">
              <img
                src={fileUrl}
                alt={document.original_filename + ", page " + (unit + 1)}
                className="max-w-none"
                style={{ width: scale * 700 + "px" }}
                onLoad={onPageRendered}
              />
              {pageReady && (
                <div className="pointer-events-none absolute inset-0">
                  {overlays}
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
              )}
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
            <pre className="font-mono max-h-[70vh] overflow-auto whitespace-pre-wrap p-2 text-sm">
              {layout?.content}
            </pre>
          )}
        </div>
      </ScrollRegion>
    </section>
  );
}
