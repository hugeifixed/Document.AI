import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckIcon, ChevronDownIcon, SparklesIcon } from "@heroicons/react/20/solid";
import { toast } from "sonner";
import { errorMessage } from "@/common/api/client";
import {
  addDocument, addSample, createSession, deleteSamples, deleteSession, generate,
  getSession, listDocuments, listSessions, saveProposal,
} from "../api/playground";
import { playgroundKeys } from "../api/query-keys";
import type { PlaygroundProposal, PlaygroundSession, PlaygroundType, ProposedDocument, ProposedField } from "../types/playground";
import { GenerationProgress } from "./generation-progress";
import { ProposalEditor } from "./proposal-editor";
import { ProposalFinish } from "./proposal-finish";
import { ProposalSwitchDialog } from "./proposal-switch-dialog";

const kinds: { value: PlaygroundType; label: string; hint: string }[] = [
  { value: "extract_structured", label: "One form", hint: "Fixed boxes and labels" },
  { value: "extract_unstructured", label: "One document with prose", hint: "Letters, notes, or agreements" },
  { value: "unbundle_classify_extract", label: "Mixed bundle", hint: "Several document types" },
];
const goals: { label: string; kind: PlaygroundType }[] = [
  { label: "Extract visible form fields", kind: "extract_structured" },
  { label: "Capture terms and obligations", kind: "extract_unstructured" },
  { label: "Separate document types", kind: "unbundle_classify_extract" },
];
const activeStatus = new Set(["queued", "analyzing", "generating"]);

type Props = {
  projectId: string;
  datasetId: string | null;
  appliedKey: number;
  onUse: (workflowType: PlaygroundType, config: Record<string, unknown>) => void;
};

export function WorkflowPlayground({ projectId, datasetId, appliedKey, onUse }: Props) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [id, setId] = useState("");
  const [kind, setKind] = useState<PlaygroundType>("extract_structured");
  const [goal, setGoal] = useState("");
  const [refinement, setRefinement] = useState("");
  const [documentSearch, setDocumentSearch] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [sessionSearch, setSessionSearch] = useState("");
  const [documentPickerOpen, setDocumentPickerOpen] = useState(false);
  const [pendingSwitch, setPendingSwitch] = useState<string | null>(null);
  const [pendingSampleChange, setPendingSampleChange] = useState<{
    action: () => Promise<PlaygroundSession>;
  } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<PlaygroundProposal | null>(null);
  const loadedProposal = useRef("");
  const loadedSession = useRef("");
  const resumeDetails = useRef<HTMLDetailsElement>(null);
  const sampleTrigger = useRef<HTMLElement | null>(null);
  const generateButton = useRef<HTMLButtonElement>(null);
  useEffect(() => { setOpen(false); }, [appliedKey]);
  useEffect(() => {
    if (pendingSampleChange || !sampleTrigger.current) return;
    const trigger = sampleTrigger.current;
    sampleTrigger.current = null;
    const timer = window.setTimeout(() => {
      if (trigger.isConnected && !trigger.hasAttribute("disabled")) trigger.focus();
      else generateButton.current?.focus();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [pendingSampleChange]);
  useEffect(() => {
    const timeout = window.setTimeout(() => setSearchTerm(documentSearch.trim()), 300);
    return () => window.clearTimeout(timeout);
  }, [documentSearch]);
  const sessions = useQuery({
    queryKey: playgroundKeys.sessions(projectId), queryFn: ({ signal }) => listSessions(projectId, signal), enabled: open,
  });
  const session = useQuery({
    queryKey: playgroundKeys.session(id), queryFn: ({ signal }) => getSession(id, signal),
    enabled: open && !!id,
    refetchInterval: (query) => activeStatus.has(query.state.data?.status || "") ? 2000 : false,
  });
  const documents = useQuery({
    queryKey: playgroundKeys.documents(datasetId, searchTerm),
    queryFn: ({ signal }) => listDocuments(datasetId!, searchTerm, signal),
    enabled: open && !!id && !!datasetId && documentPickerOpen,
  });
  const current = session.data;
  const processing = activeStatus.has(current?.status || "");
  const sampleLimitReached = (current?.samples.length ?? 0) >= 3;
  const proposalHasEdits = !!current && !!draft && JSON.stringify(draft) !== JSON.stringify(current.proposal);
  const hasUnsavedEdits = !!current && (
    proposalHasEdits ||
    goal !== current.goal || kind !== (current.workflow_type || "extract_structured") || !!refinement.trim()
  );
  const matchingSessions = sessions.data
    ?.filter((item) => `${item.goal} ${item.status}`.toLocaleLowerCase().includes(sessionSearch.toLocaleLowerCase()))
    .sort((a, b) => Date.parse(b.last_activity_at) - Date.parse(a.last_activity_at)) ?? [];
  const eligibleDocuments = documents.data?.results.filter((doc) =>
    ["validated", "processed", "failed"].includes(doc.status)
  ) ?? [];
  const selectedDocumentIds = new Set(current?.samples.map((sample) => sample.document_id).filter(Boolean));
  useEffect(() => {
    if (!current || loadedSession.current === current.id) return;
    loadedSession.current = current.id;
    setKind(current.workflow_type || "extract_structured");
    setGoal(current.goal);
    setRefinement("");
  }, [current]);
  useEffect(() => {
    if (!current) return;
    if (!("documents" in current.proposal)) {
      loadedProposal.current = "";
      setDraft(null);
      return;
    }
    const serialized = JSON.stringify(current.proposal);
    if (serialized !== loadedProposal.current) {
      loadedProposal.current = serialized;
      setDraft(structuredClone(current.proposal as PlaygroundProposal));
    }
  }, [current]);
  const refresh = async (next?: PlaygroundSession) => {
    if (next) queryClient.setQueryData(playgroundKeys.session(next.id), next);
    await queryClient.invalidateQueries({ queryKey: playgroundKeys.sessions(projectId) });
    // Mutations return the full session. Avoid an immediate second fetch while the
    // document picker is updating its selected rows.
    if (!next && id) await queryClient.invalidateQueries({ queryKey: playgroundKeys.session(id) });
  };
  const act = async (action: () => Promise<PlaygroundSession | void>) => {
    if (busy) return;
    setBusy(true);
    setActionError(null);
    try { await refresh((await action()) || undefined); }
    catch (error) { setActionError(errorMessage(error)); }
    finally { setBusy(false); }
  };
  const start = () => void act(async () => {
    if (!projectId) return;
    const created = await createSession(projectId);
    setId(created.id);
    setDraft(null);
    loadedProposal.current = "";
    loadedSession.current = "";
    setKind("extract_structured");
    setGoal("");
    setRefinement("");
    setDocumentSearch("");
    return created;
  });
  const switchTo = (next: string) => {
    setActionError(null);
    resumeDetails.current?.removeAttribute("open");
    if (next === "new") { start(); return; }
    setId(next);
    setDraft(null);
    loadedProposal.current = "";
    loadedSession.current = "";
    setKind("extract_structured");
    setGoal("");
    setRefinement("");
    setDocumentSearch("");
  };
  const requestSwitch = (next: string) => {
    if (hasUnsavedEdits) setPendingSwitch(next);
    else switchTo(next);
  };
  const requestSampleChange = (action: () => Promise<PlaygroundSession>) => {
    const apply = async () => {
      const next = await action();
      setRefinement("");
      return next;
    };
    if (current && "documents" in current.proposal) {
      sampleTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setPendingSampleChange({ action: apply });
    }
    else void act(apply);
  };
  const changeField = (docIndex: number, fieldIndex: number, patch: Partial<ProposedField>) => {
    setDraft((old) => {
      if (!old) return old;
      const updated = structuredClone(old);
      Object.assign(updated.documents[docIndex].fields[fieldIndex], patch);
      return updated;
    });
  };
  const changeDocument = (docIndex: number, patch: Partial<ProposedDocument>) => setDraft((old) => {
    if (!old) return old;
    const updated = structuredClone(old);
    Object.assign(updated.documents[docIndex], patch);
    return updated;
  });
  const removeField = (docIndex: number, fieldIndex: number) => setDraft((old) => {
    if (!old) return old;
    const updated = structuredClone(old);
    updated.documents[docIndex].fields.splice(fieldIndex, 1);
    return updated;
  });
  const addField = (docIndex: number) => setDraft((old) => {
    if (!old) return old;
    const updated = structuredClone(old);
    updated.documents[docIndex].fields.push({
      name: "", description: "", type: "string", required: false, observed: false,
      sample_index: null, unit: null, source_label: "", variable_rows: false, guidance: "", enum_values: [],
    });
    return updated;
  });
  const validated = async () => {
    if (!id || !draft) throw new Error("Wait for a proposal before continuing.");
    const saved = await saveProposal(id, draft);
    await refresh(saved);
    if (!saved.config) throw new Error("The proposal did not produce valid configuration.");
    return saved;
  };

  return (
    <section className="lg:col-span-2 rounded-box border border-base-300 bg-base-100 p-5" aria-label="Workflow assistant">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-section-title">Generate with assistant</h2>
          <p className="text-sm text-secondary">Describe a goal or provide examples, then review every proposed field.</p>
        </div>
        <button type="button" className="btn btn-outline" aria-expanded={open} onClick={() => setOpen(!open)}>
          <SparklesIcon className="size-5" aria-hidden="true" />
          {open ? "Close assistant" : "Open assistant"}
        </button>
      </div>
      {open && (
        <div className="mt-5 grid gap-5">
          <div className="min-w-0 rounded-box border border-base-300 bg-base-200 p-4">
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-caption text-secondary">Current proposal</p>
                <p className="line-clamp-2 min-w-0 font-medium [overflow-wrap:anywhere] text-pretty" title={current?.goal || undefined}>
                  {id ? current?.goal || "Untitled proposal" : "Start a proposal or resume one below"}
                </p>
              </div>
              <button type="button" className="btn btn-outline min-h-10" onClick={() => requestSwitch("new")}
                disabled={busy || !projectId}>New proposal</button>
            </div>
            <details ref={resumeDetails} className="mt-3 border-t border-base-300 pt-3">
              <summary className="cursor-pointer font-medium">Resume a proposal</summary>
              <div className="mt-3 grid min-w-0 gap-2">
                <label htmlFor="playground-session-search" className="text-sm">Find by goal or status</label>
                <input id="playground-session-search" type="search" className="input border-(--border-interactive) w-full"
                  value={sessionSearch} onChange={(event) => setSessionSearch(event.target.value)} />
                <div className="max-h-56 overflow-y-auto rounded-box border border-base-300 bg-base-100">
                  {sessions.isPending && <p className="p-3 text-sm text-secondary">Loading proposals…</p>}
                  {sessions.isError && <p role="alert" className="p-3 text-sm text-error">Could not load proposals.
                    <button type="button" className="btn btn-ghost min-h-10 ml-2" onClick={() => void sessions.refetch()}>Retry</button>
                  </p>}
                  {!sessions.isPending && !sessions.isError && matchingSessions.length === 0 &&
                    <p className="p-3 text-sm text-secondary">No matching proposals.</p>}
                  {matchingSessions.map((item) => (
                    <button key={item.id} type="button" disabled={busy} onClick={() => requestSwitch(item.id)}
                      aria-current={id === item.id ? "true" : undefined}
                      className={`flex min-h-12 w-full min-w-0 items-center justify-between gap-3 border-b border-base-300 px-3 py-2 text-left last:border-b-0 hover:bg-base-200 focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary ${id === item.id ? "bg-base-200" : ""}`}>
                      <span className="line-clamp-2 min-w-0 flex-1 [overflow-wrap:anywhere] text-sm" title={item.goal}>{item.goal || "Untitled proposal"}</span>
                      <span className="shrink-0 text-right text-caption text-secondary">{item.status}<br />Updated {new Date(item.last_activity_at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
                    </button>
                  ))}
                </div>
              </div>
            </details>
          </div>
          {id && (
            <>
              <fieldset disabled={processing} className="grid gap-3 md:grid-cols-3">
                <legend className="sr-only">Document shape</legend>
                {kinds.map((option) => <label key={option.value} className="flex cursor-pointer items-start gap-2 rounded-box border border-base-300 p-3">
                  <input id={`playground-${option.value}`} aria-label={option.label} type="radio" className="radio radio-sm" checked={kind === option.value}
                    onChange={() => setKind(option.value)} name="playground-kind" />
                  <span><strong className="block">{option.label}</strong><span className="text-caption text-secondary">{option.hint}</span></span>
                </label>)}
              </fieldset>
              <div>
                <label htmlFor="playground-goal" className="block font-medium">What should this workflow do?</label>
                <textarea id="playground-goal" className="textarea border-(--border-interactive) mt-2 w-full" rows={2}
                  readOnly={processing} aria-readonly={processing}
                  maxLength={1000} value={goal} onChange={(event) => setGoal(event.target.value)}
                  placeholder="A few words are enough; samples can show the fields." />
                <div className="mt-2 flex flex-wrap gap-2">
                  {goals.map((chip) => <button key={chip.label} type="button" className="btn btn-outline min-h-10" disabled={processing}
                    onClick={() => { setKind(chip.kind); setGoal(chip.label); }}>{chip.label}</button>)}
                </div>
              </div>
              <div className="rounded-box border border-base-300 p-4">
                <h3 className="font-medium">Examples</h3>
                <p className="text-sm text-secondary">Up to 3 samples, 30 pages or sheets and 50 MB total. New uploads are temporary and expire after 24 hours.</p>
                <div className="mt-3 grid gap-3 md:grid-cols-2 md:items-start">
                  <label className="grid min-w-0 gap-1 text-sm">Upload a private sample
                    <input className="file-input border-(--border-interactive) w-full min-w-0" type="file"
                      disabled={processing || sampleLimitReached} aria-disabled={busy || processing || sampleLimitReached}
                      onClick={(event) => { if (busy) event.preventDefault(); }}
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file && !busy && !sampleLimitReached) requestSampleChange(() => addSample(id, file));
                        event.target.value = "";
                      }} />
                  </label>
                  {datasetId && (
                    <div className="min-w-0 text-sm">
                      <span className="mb-1 block">Or use a dataset document</span>
                      <details className="group min-w-0 rounded-lg border border-(--border-interactive) bg-base-100" onToggle={(event) => setDocumentPickerOpen(event.currentTarget.open)}>
                      <summary className="flex min-h-10 cursor-pointer list-none items-center justify-between gap-2 px-3 font-medium [&::-webkit-details-marker]:hidden">
                        <span>Choose a dataset document</span>
                        <ChevronDownIcon className="size-4 shrink-0 motion-safe:transition-transform motion-safe:duration-180 group-open:rotate-180" aria-hidden="true" />
                      </summary>
                      <div className="grid min-w-0 gap-2 border-t border-base-300 p-3">
                        <label htmlFor="playground-document-search" className="text-sm">Search eligible documents in this dataset</label>
                        <input id="playground-document-search" type="search" className="input border-(--border-interactive) w-full"
                          readOnly={processing} aria-readonly={processing}
                          value={documentSearch} onChange={(event) => setDocumentSearch(event.target.value)}
                          placeholder="Search by file name" />
                        <div className="max-h-56 overflow-y-auto rounded-box border border-base-300">
                          {documents.isPending && <p className="p-3 text-sm text-secondary">Loading documents…</p>}
                          {documents.isError && <p role="alert" className="p-3 text-sm text-error">Could not load dataset documents.
                            <button type="button" className="btn btn-ghost min-h-10 ml-2" onClick={() => void documents.refetch()}>Retry</button>
                          </p>}
                          {!documents.isPending && !documents.isError && eligibleDocuments.length === 0 &&
                            <p className="p-3 text-sm text-secondary">No eligible documents found. Try another file name or upload a private sample.</p>}
                          {eligibleDocuments.slice(0, 20).map((doc) => {
                            const selected = selectedDocumentIds.has(doc.id);
                            return <button key={doc.id} type="button"
                              className={`flex min-h-12 w-full min-w-0 items-center justify-between gap-3 border-b border-base-300 px-3 py-2 text-left last:border-b-0 focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary ${selected ? "bg-(--color-blue-soft)" : sampleLimitReached ? "cursor-not-allowed text-secondary" : "hover:bg-base-200"}`}
                              aria-disabled={selected || busy || processing || sampleLimitReached}
                              onClick={() => { if (!selected && !busy && !processing && !sampleLimitReached) requestSampleChange(() => addDocument(id, doc.id)); }}>
                              <span className="min-w-0 flex-1 truncate text-sm" title={doc.original_filename}>{doc.original_filename}</span>
                              <span className={`flex shrink-0 items-center gap-1 text-caption ${selected ? "font-medium text-primary" : "text-secondary"}`}>
                                {selected && <CheckIcon className="size-4" aria-hidden="true" />}
                                {selected ? "Selected" : sampleLimitReached ? "Limit reached" : "Add"}
                              </span>
                            </button>;
                          })}
                        </div>
                        {eligibleDocuments.length > 20 && <p className="text-caption text-secondary">Showing 20 matches. Refine the search to find another file.</p>}
                      </div>
                      </details>
                    </div>
                  )}
                </div>
                {!!current?.samples.length && <ul className="mt-3 grid gap-1 text-sm" aria-label="Selected examples">
                  {current.samples.map((sample) => <li key={sample.id} className="flex min-w-0 flex-wrap items-center gap-x-2 rounded-lg border border-base-300 px-3 py-2">
                    <CheckIcon className="size-4 shrink-0 text-primary" aria-hidden="true" />
                    <span className="min-w-0 [overflow-wrap:anywhere]">{sample.filename}</span>
                    <span className="text-caption text-secondary">{sample.units} page(s)/sheet(s) · {sample.source_kind === "temporary" ? "Private sample" : "Dataset document"}</span>
                  </li>)}
                </ul>}
                {!!current?.samples.length && <button type="button" className="btn btn-ghost min-h-10 mt-3"
                  disabled={busy || processing} onClick={() => requestSampleChange(() => deleteSamples(id))}>Clear examples</button>}
                {sampleLimitReached && <output className="mt-2 block text-caption text-secondary">
                  3 of 3 examples selected. Clear examples to choose a different set.
                </output>}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <button ref={generateButton} type="button" className="btn btn-outline" disabled={processing} aria-disabled={busy || processing}
                  onClick={() => { if (!busy && !processing) void act(() => generate(id, { goal, workflow_type: kind })); }}>
                  {processing ? "Generating…" : "Generate proposal"}
                </button>
                {!processing && <output className="text-sm text-secondary" aria-live="polite">
                  {current?.status === "failed" ? current.error_message :
                          current?.status === "complete" ? "Proposal ready for review" : ""}
                </output>}
              </div>
              {processing && <GenerationProgress stage={current!.status as "queued" | "analyzing" | "generating"}
                hasExamples={!!current?.samples.length} />}
              {actionError && <p role="alert" className="rounded-box border border-error bg-(--color-error-soft) p-3 text-sm text-error [overflow-wrap:anywhere]">{actionError}</p>}
              {current?.status === "complete" && draft && (
                <div className="grid gap-5">
                  <ProposalEditor proposal={draft} onDocumentChange={changeDocument} onFieldChange={changeField}
                    onRemoveField={removeField} onAddField={addField} />
                  <ProposalFinish busy={busy} config={current.config} proposalHasEdits={proposalHasEdits}
                    refinement={refinement} onRefinementChange={setRefinement}
                    onRefine={() => void act(async () => {
                      const nextRefinement = refinement.trim();
                      await validated();
                      const next = await generate(id, { goal, workflow_type: kind, refinement: nextRefinement });
                      setRefinement("");
                      return next;
                    })}
                    onUpdatePreview={() => void act(async () => validated())}
                    onCopy={() => void act(async () => {
                      const saved = await validated();
                      await navigator.clipboard.writeText(JSON.stringify(saved.config, null, 2));
                      toast.success("Type-specific JSON copied");
                    })}
                    onUse={() => void act(async () => {
                      const saved = await validated();
                      onUse(saved.workflow_type as PlaygroundType, saved.config!);
                    })} />
                </div>
              )}
              <div className="flex flex-wrap items-center justify-between gap-2 text-caption text-secondary">
                <span>Expires {current?.expires_at ? new Date(current.expires_at).toLocaleString() : "after 24 hours"}
                  {current && ` · ${current.usage.input_tokens} input tokens (${current.usage.cached_input_tokens} cached), ${current.usage.output_tokens} output tokens`}
                </span>
                <button type="button" className="btn btn-ghost min-h-10" disabled={busy || activeStatus.has(current?.status || "")}
                  onClick={() => void act(async () => { await deleteSession(id); setId(""); setDraft(null); loadedProposal.current = ""; })}>
                  Delete proposal
                </button>
              </div>
            </>
          )}
        </div>
      )}
      <ProposalSwitchDialog open={pendingSwitch !== null} onClose={() => setPendingSwitch(null)}
        onConfirm={() => { if (pendingSwitch) switchTo(pendingSwitch); setPendingSwitch(null); }} />
      <ProposalSwitchDialog open={pendingSampleChange !== null}
        title="Change examples?"
        description="Changing examples clears the current proposal and unsaved field edits. Generate again after choosing examples."
        confirmLabel="Change examples"
        onClose={() => setPendingSampleChange(null)}
        onConfirm={() => {
          const pending = pendingSampleChange;
          setPendingSampleChange(null);
          if (pending) void act(pending.action);
        }} />
    </section>
  );
}
