/** Review + labeling workspace (§10.3). Left: the document (react-pdf, image, or sheet grid)
 *  with overlays from stored spans. Right: the field panel. In label mode, a text selection
 *  on the PDF.js text layer becomes a PDF-space rect set → POST /labels (mode pdfjs); pages
 *  without a text layer use word-box selection; sheets use cell ranges. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Document as PdfDocument, Page as PdfPage, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { useSession } from "@/auth/Session";
import { ErrorNotice } from "@/components/ErrorNotice";
import { announce } from "@/a11y/announce";
import { ApiError, get, list, post } from "@/api/client";
import type { Document, ExtractedField, Label, LayoutUnit, Run, Span } from "@/api/types";
import { Breadcrumbs, ConfidenceCue, EmptyState, StatusChip } from "@/components/ui";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

type Rect = { x: number; y: number; width: number; height: number };
interface Selection { unit: number; text: string; rects: Rect[]; pageW: number; pageH: number }

function Overlay({ polygon, selected, label }: { polygon: number[]; selected?: boolean; label: string }) {
  if (polygon.length < 8) return null;
  const xs = polygon.filter((_, i) => i % 2 === 0), ys = polygon.filter((_, i) => i % 2 === 1);
  const l = Math.min(...xs) * 100, t = Math.min(...ys) * 100, w = (Math.max(...xs) - Math.min(...xs)) * 100, h = (Math.max(...ys) - Math.min(...ys)) * 100;
  return <div className={`overlay-box ${selected ? "selected" : ""}`} style={{ left: `${l}%`, top: `${t}%`, width: `${w}%`, height: `${h}%` }} aria-hidden="true" title={label} />;
}

export function ReviewWorkspace({ mode }: { mode: "review" | "label" }) {
  const { documentId } = useParams(); const [sp, setSp] = useSearchParams(); const qc = useQueryClient();
  const { user } = useSession();
  const doc = useQuery({ queryKey: ["document", documentId], queryFn: () => get<Document>(`/documents/${documentId}/`) });
  const runId = sp.get("run");
  const runs = useQuery({ queryKey: ["runs-for-doc", documentId], queryFn: () => list<Run>("/runs/", { page_size: 20, ordering: "-created", dataset: doc.data?.dataset }), enabled: !!doc.data });
  const activeRun = runId ?? runs.data?.results[0]?.id;
  const fields = useQuery({ queryKey: ["fields", documentId, activeRun], enabled: !!activeRun, queryFn: () => list<ExtractedField>("/fields/", { document: documentId, run: activeRun, page_size: 200, ordering: "name" }) });
  const labels = useQuery({ queryKey: ["labels", documentId], queryFn: () => list<Label>("/labels/", { document: documentId, page_size: 200 }) });
  const [unit, setUnit] = useState(0);
  const [selectedField, setSelectedField] = useState<string | null>(sp.get("field"));
  const layout = useQuery({ queryKey: ["unit", documentId, unit], queryFn: () => get<LayoutUnit>(`/documents/${documentId}/units/${unit}/`), enabled: !!doc.data && (doc.data.units?.length ?? 0) > 0 });
  const [scale, setScale] = useState(1.1);
  const [sel, setSel] = useState<Selection | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [cellRange, setCellRange] = useState("");
  const [fieldName, setFieldName] = useState(""); const [expected, setExpected] = useState(""); const [notes, setNotes] = useState("");
  const pageRef = useRef<HTMLDivElement>(null);
  const units = doc.data?.units ?? [];
  const isSheet = doc.data?.file_format === "xlsx" || doc.data?.file_format === "xls";
  const isPdf = doc.data?.file_format === "pdf"; const isImage = ["png", "jpeg", "tiff"].includes(doc.data?.file_format ?? "");
  const canSee = !!user && user.roles.some((r) => ["docai_operators", "docai_reviewers", "docai_approvers"].includes(r));
  const canReview = !!user?.roles.includes("docai_reviewers");
  const canApprove = !!user?.roles.includes("docai_approvers");
  const spansOnUnit: Span[] = useMemo(() => {
    const fromFields = (fields.data?.results ?? []).flatMap((f) => f.spans.filter((s) => s.unit_index === unit).map((s) => ({ ...s, text: `${f.name}: ${f.raw_value ?? ""}`, id: f.id })));
    const fromLabels = (labels.data?.results ?? []).flatMap((l) => l.spans.filter((s) => s.unit_index === unit).map((s) => ({ ...s, text: `label ${l.field_name}`, id: `label-${l.id}` })));
    return [...fromFields, ...fromLabels];
  }, [fields.data, labels.data, unit]);
  const schemaFields = useMemo(() => Array.from(new Set((fields.data?.results ?? []).map((f) => f.name))), [fields.data]);

  // jump to the selected field's page
  useEffect(() => { const f = fields.data?.results.find((x) => x.id === selectedField); const u = f?.spans[0]?.unit_index; if (u != null) setUnit(u); }, [selectedField, fields.data]);

  // §10.3 label mode: capture PDF.js text selection → rects in PDF user space (points, bottom-left origin)
  const onMouseUp = useCallback(() => {
    if (mode !== "label" || !isPdf || !layout.data?.width || !layout.data?.height) return;
    const s = window.getSelection(); const el = pageRef.current?.querySelector(".react-pdf__Page");
    if (!s || s.isCollapsed || !el || !el.contains(s.anchorNode)) return;
    const page = el.getBoundingClientRect(); const range = s.getRangeAt(0);
    const k = layout.data.width / page.width;   // CSS px → PDF points
    const rects: Rect[] = Array.from(range.getClientRects()).filter((r) => r.width > 1 && r.height > 1).map((r) => ({
      x: (r.left - page.left) * k, y: layout.data!.height! - (r.bottom - page.top) * k, width: r.width * k, height: r.height * k }));
    if (!rects.length) return;
    const text = s.toString().replace(/\s+/g, " ").trim();
    setSel({ unit, text, rects, pageW: layout.data.width, pageH: layout.data.height }); setExpected(text);
    announce(`Selected "${text.slice(0, 60)}"`);
  }, [mode, isPdf, layout.data, unit]);

  useEffect(() => { document.addEventListener("mouseup", onMouseUp); document.addEventListener("keyup", onMouseUp); return () => { document.removeEventListener("mouseup", onMouseUp); document.removeEventListener("keyup", onMouseUp); }; }, [onMouseUp]);

  const createLabel = useMutation({
    mutationFn: () => {
      const base = { document: documentId, field_name: fieldName, expected_value: expected, notes, unit_index: unit };
      if (isSheet) return post<Label>("/labels/", { ...base, mode: "cells", cell_range: cellRange });
      if (layout.data && layout.data.has_text_layer === false) return post<Label>("/labels/", { ...base, mode: "word_ids", word_ids: picked });
      if (!sel) throw new ApiError(0, { message: "Select text on the page first." });
      return post<Label>("/labels/", { ...base, mode: "pdfjs", text: sel.text, rects: sel.rects, page_width_pt: sel.pageW, page_height_pt: sel.pageH });
    },
    onSuccess: (l) => { toast.success(`Label saved · ${l.mapping_method} (${l.match_score != null ? Math.round(l.match_score * 100) + "%" : "n/a"})${l.mapping_exceptions.length ? " — " + l.mapping_exceptions[0] : ""}`); setSel(null); setPicked([]); setCellRange(""); qc.invalidateQueries({ queryKey: ["labels", documentId] }); },
    onError: (e: ApiError) => toast.error(`${e.message}${e.code ? ` (${e.code})` : ""}`),
  });
  const markAbsent = useMutation({ mutationFn: () => post<Label>("/labels/", { document: documentId, mode: "absent", field_name: fieldName, notes }), onSuccess: () => { toast.success("Marked absent"); qc.invalidateQueries({ queryKey: ["labels", documentId] }); }, onError: (e: ApiError) => toast.error(e.message) });
  const review = useMutation({ mutationFn: ({ id, action, value }: { id: string; action: string; value?: string }) => post(`/fields/${id}/review/`, { action, value, reason: "reviewed in workspace" }),
    onSuccess: (_, v) => { toast.success(`Field ${v.action === "promote" ? "promoted to ground truth" : v.action + "ed"}`); qc.invalidateQueries({ queryKey: ["fields"] }); qc.invalidateQueries({ queryKey: ["labels", documentId] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); }, onError: (e: ApiError) => toast.error(`${e.message} (${e.code})`) });

  if (doc.error) return <ErrorNotice message={doc.error.message} onRetry={() => void doc.refetch()} />;
  if (!doc.data) return <output className="block">Loading…</output>;
  if (mode === "label" && !canReview) return <div><Breadcrumbs items={[{ label: "Ground truth", to: "/labeling" }, { label: doc.data.original_filename }]} /><EmptyState text="Creating ground truth requires the reviewer role." action={<Link className="btn btn-outline btn-sm" to="/results">View extracted results</Link>} /></div>;
  if (!canSee) return <div><Breadcrumbs items={[{ label: "Extracted results", to: "/results" }, { label: doc.data.original_filename }]} /><EmptyState text="Viewing document content requires the operator, reviewer, or approver role." action={<Link className="btn btn-outline btn-sm" to="/results">Back to extracted results</Link>} /></div>;
  const fileUrl = `/api/v1/documents/${documentId}/original/`;
  return (
    <div>
      <Breadcrumbs items={[{ label: mode === "label" ? "Ground truth" : "Review queue", to: mode === "label" ? "/labeling" : "/review" }, { label: doc.data.original_filename }]} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section aria-label="Document" className="min-w-0 rounded-box border border-base-300 bg-base-100 p-3">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
          <h1 className="text-section-title">{doc.data.original_filename}</h1>
          <label className="ml-auto flex min-w-0 max-w-full flex-wrap items-center gap-1">{isSheet ? "Sheet" : "Page"}<select className="select border-(--border-interactive) select-xs" value={unit} onChange={(e) => setUnit(Number(e.target.value))}>{units.map((u) => <option key={u.id} value={u.index}>{u.label}</option>)}</select></label>
          {!isSheet && <><button type="button" className="btn btn-xs btn-outline" onClick={() => setScale((s) => Math.max(0.5, s - 0.2))} aria-label="Zoom out">−</button><span className="tabular-nums">{Math.round(scale * 100)}%</span><button type="button" className="btn btn-xs btn-outline" onClick={() => setScale((s) => Math.min(3, s + 0.2))} aria-label="Zoom in">+</button></>}
          {activeRun && <label className="flex min-w-0 max-w-full flex-wrap items-center gap-1">Run<select className="select border-(--border-interactive) select-xs" value={activeRun} onChange={(e) => { sp.set("run", e.target.value); setSp(sp, { replace: true }); }}>{runs.data?.results.map((r) => <option key={r.id} value={r.id}>{r.name || r.workflow_name}</option>)}</select></label>}
        </div>
        {mode === "label" && isPdf && layout.data?.has_text_layer !== false && <p className="mb-2 text-sm text-secondary">Select text on the page with the mouse or keyboard (Shift+arrows in the text layer), then fill in the field on the right.</p>}
        {mode === "label" && layout.data?.has_text_layer === false && <p className="mb-2 text-sm text-secondary">This page has no text layer: click word boxes to build the selection.</p>}
        <div ref={pageRef} className="relative inline-block max-w-full overflow-auto">
          {isPdf && (
            <PdfDocument file={fileUrl} loading={<output className="block">Rendering…</output>} error={<p role="alert">The PDF could not be rendered.</p>}>
              <div className="relative">
                <PdfPage pageNumber={unit + 1} scale={scale} renderTextLayer renderAnnotationLayer={false} />
                <div className="pointer-events-none absolute inset-0">
                  {spansOnUnit.map((s) => <Overlay key={s.id + s.text} polygon={s.polygon} selected={s.id === selectedField} label={s.text} />)}
                  {layout.data?.has_text_layer === false && layout.data.words?.map((w) => { const xs = w.polygon.filter((_, i) => i % 2 === 0), ys = w.polygon.filter((_, i) => i % 2 === 1); return (
                    <button type="button" key={w.id} className={`overlay-word pointer-events-auto ${picked.includes(w.id) ? "picked" : ""}`} aria-pressed={picked.includes(w.id)} aria-label={`word ${w.text}`}
                      style={{ left: `${Math.min(...xs) * 100}%`, top: `${Math.min(...ys) * 100}%`, width: `${(Math.max(...xs) - Math.min(...xs)) * 100}%`, height: `${(Math.max(...ys) - Math.min(...ys)) * 100}%` }}
                      onClick={() => setPicked((p) => (p.includes(w.id) ? p.filter((x) => x !== w.id) : [...p, w.id]))} />); })}
                </div>
              </div>
            </PdfDocument>)}
          {isImage && <div className="relative"><img src={fileUrl} alt={`${doc.data.original_filename}, page ${unit + 1}`} style={{ width: `${scale * 700}px` }} /><div className="pointer-events-none absolute inset-0">{spansOnUnit.map((s) => <Overlay key={s.id} polygon={s.polygon} selected={s.id === selectedField} label={s.text} />)}
            {layout.data?.words?.map((w) => { const xs = w.polygon.filter((_, i) => i % 2 === 0), ys = w.polygon.filter((_, i) => i % 2 === 1); return mode === "label" ? <button type="button" key={w.id} className={`overlay-word pointer-events-auto ${picked.includes(w.id) ? "picked" : ""}`} aria-pressed={picked.includes(w.id)} aria-label={`word ${w.text}`} style={{ left: `${Math.min(...xs) * 100}%`, top: `${Math.min(...ys) * 100}%`, width: `${(Math.max(...xs) - Math.min(...xs)) * 100}%`, height: `${(Math.max(...ys) - Math.min(...ys)) * 100}%` }} onClick={() => setPicked((p) => (p.includes(w.id) ? p.filter((x) => x !== w.id) : [...p, w.id]))} /> : null; })}</div></div>}
          {isSheet && layout.data?.cells && (
            <div className="overflow-auto"><table className="table table-xs font-mono"><caption className="sr-only">Sheet {layout.data.name}</caption>
              <tbody>{Array.from({ length: layout.data.row_count ?? 0 }).map((_, r) => <tr key={r}><th scope="row">{r + 1}</th>{Array.from({ length: layout.data!.col_count ?? 0 }).map((__, c) => { const cell = layout.data!.cells!.find((x) => x.row === r && x.col === c); const hit = spansOnUnit.some((s) => cell && s.word_ids.includes(cell.id)); return (
                <td key={c} className={`${hit ? "bg-info/20" : ""} ${cellRange === cell?.ref ? "ring-2 ring-primary" : ""}`} title={cell?.formula ?? undefined}>{mode === "label" && cell ? <button type="button" className="w-full text-left" onClick={() => setCellRange(cell.ref)} aria-label={`cell ${cell.ref} ${cell.value ?? ""}`}>{cell.value}</button> : cell?.value}</td>); })}</tr>)}</tbody></table></div>)}
          {!isPdf && !isImage && !isSheet && <pre className="font-mono max-h-[70vh] overflow-auto whitespace-pre-wrap p-2 text-sm">{layout.data?.content}</pre>}
        </div>
      </section>
      <aside aria-label={mode === "label" ? "Ground truth" : "Fields"} className="min-w-0 rounded-box border border-base-300 bg-base-100 p-3">
        {mode === "label" ? (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (!fieldName) { toast.error("Enter a field name."); return; } createLabel.mutate(); }}>
            <h2>New label</h2>
            <div className="fieldset min-w-0 gap-2 p-0 text-sm"><label className="label whitespace-normal font-medium text-base-content" htmlFor="reviewworkspace-field-name">Field name <span aria-hidden>*</span></label><input id="reviewworkspace-field-name" className="input input-sm w-full border-(--border-interactive)" list="schema-fields" aria-label="Field name" value={fieldName} onChange={(e) => setFieldName(e.target.value)} required /><datalist id="schema-fields">{schemaFields.map((f) => <option key={f} value={f}>{f}</option>)}</datalist></div>
            <div className="fieldset min-w-0 gap-2 p-0 text-sm"><label className="label whitespace-normal font-medium text-base-content" htmlFor="reviewworkspace-expected-value">Expected value</label><input id="reviewworkspace-expected-value" className="input input-sm w-full border-(--border-interactive) font-mono" value={expected} onChange={(e) => setExpected(e.target.value)} /></div>
            {isSheet && <div className="fieldset min-w-0 gap-2 p-0 text-sm"><label className="label whitespace-normal font-medium text-base-content" htmlFor="reviewworkspace-cell-range">Cell range</label><input id="reviewworkspace-cell-range" className="input input-sm w-full border-(--border-interactive) font-mono" value={cellRange} onChange={(e) => setCellRange(e.target.value.toUpperCase())} placeholder="B3 or B3:C3" /></div>}
            {!isSheet && layout.data?.has_text_layer !== false && <p className="text-sm">{sel ? <>Selection on page {sel.unit + 1}: <span className="font-mono">{sel.text.slice(0, 80)}</span> ({sel.rects.length} rect{sel.rects.length === 1 ? "" : "s"})</> : "No selection yet."}</p>}
            {layout.data?.has_text_layer === false && <p className="text-sm">{picked.length} word box(es) picked.</p>}
            <div className="fieldset min-w-0 gap-2 p-0 text-sm"><label className="label whitespace-normal font-medium text-base-content" htmlFor="reviewworkspace-notes">Notes</label><input id="reviewworkspace-notes" className="input input-sm w-full border-(--border-interactive)" value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
            <div className="flex flex-wrap gap-2"><button className="btn btn-primary btn-sm" disabled={createLabel.isPending}>Save label</button><button type="button" className="btn btn-outline btn-sm" onClick={() => fieldName ? markAbsent.mutate() : toast.error("Enter a field name.")}>Mark absent</button></div>
            <h3 className="mt-4">Labels on this document</h3>
            <ul className="space-y-1 text-sm">{labels.data?.results.map((l) => <li key={l.id} className="flex items-center justify-between gap-2 rounded border px-2 py-1 border-base-300"><span><strong>{l.field_name || l.category}</strong> {l.is_absent ? <em>absent</em> : <span className="font-mono">{l.expected_value}</span>}</span><span className="text-caption text-secondary">v{l.version} · {l.mapping_method}{l.match_score != null ? ` ${Math.round(l.match_score * 100)}%` : ""} · <StatusChip status={l.status === "final" ? "accepted" : l.status} /></span></li>)}</ul>
          </form>
        ) : (
          <div>
            <h2 className="mb-2">Fields{fields.data ? ` (${fields.data.count})` : ""}</h2>
            {!activeRun && <p className="text-sm">No run has processed this document yet.</p>}
            <ul className="space-y-2">
              {fields.data?.results.map((f) => (
                <li key={f.id} className={`rounded-box border p-2 ${selectedField === f.id ? "ring-2 ring-primary" : ""} border-base-300`}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <button type="button" className="min-w-0 max-w-full text-left [overflow-wrap:anywhere]" onClick={() => setSelectedField(f.id)} aria-pressed={selectedField === f.id}><div className="text-sm font-semibold">{f.name}</div><div className="font-mono text-sm">{f.reviewed_value ?? f.raw_value ?? <em className="text-secondary">not found</em>}</div></button>
                    <div className="ml-auto text-right"><ConfidenceCue score={f.score} status={f.review_status} label={f.name} /><div><StatusChip status={f.review_status} /></div></div>
                  </div>
                  {f.source_text && <div className="mt-1 text-caption text-secondary">evidence: “{f.source_text.slice(0, 80)}”{f.spans[0] ? ` · p${f.spans[0].unit_index + 1} · ${f.spans[0].mapping_method}` : " · not grounded"}</div>}
                  {f.validation_messages.length > 0 && <div className="mt-1 text-caption text-warning">{f.validation_messages.join("; ")}{f.suggested_correction && <> · suggested: <span className="font-mono">{f.suggested_correction}</span></>}</div>}
                  <div className="mt-2 flex flex-wrap gap-1">
                    {canReview && <><button type="button" className="btn btn-xs btn-outline" onClick={() => review.mutate({ id: f.id, action: "accept" })}>Accept</button>
                    <button type="button" className="btn btn-xs btn-outline" onClick={() => { const v = window.prompt(`Corrected value for ${f.name}`, f.reviewed_value ?? f.raw_value ?? ""); if (v !== null) review.mutate({ id: f.id, action: "correct", value: v }); }}>Correct</button>
                    <button type="button" className="btn btn-xs btn-outline" onClick={() => review.mutate({ id: f.id, action: "mark_absent" })}>Absent</button>
                    <button type="button" className="btn btn-xs btn-ghost" onClick={() => review.mutate({ id: f.id, action: "reject" })}>Reject</button></>}
                    {["accepted", "corrected", "absent"].includes(f.review_status) && canApprove && <button type="button" className="btn btn-xs btn-primary" onClick={() => review.mutate({ id: f.id, action: "promote" })}>Promote to ground truth</button>}
                  </div>
                </li>))}
            </ul>
          </div>
        )}
      </aside>
      </div>
    </div>
  );
}
