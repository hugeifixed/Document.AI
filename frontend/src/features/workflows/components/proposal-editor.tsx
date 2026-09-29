import { type Dispatch, type SetStateAction, useState } from "react";
import { ChevronRightIcon } from "@heroicons/react/20/solid";
import type { PlaygroundProposal, ProposedDocument, ProposedField } from "../types/playground";

const fieldTypes = ["string", "number", "integer", "date", "boolean", "currency", "percent", "identifier", "enum", "list"] as const;
const initialFieldCount = 10;

type Props = {
  proposal: PlaygroundProposal;
  onDocumentChange: (index: number, patch: Partial<ProposedDocument>) => void;
  onFieldChange: (documentIndex: number, fieldIndex: number, patch: Partial<ProposedField>) => void;
  onRemoveField: (documentIndex: number, fieldIndex: number) => void;
  onAddField: (documentIndex: number) => void;
};

export function ProposalEditor({ proposal, onDocumentChange, onFieldChange, onRemoveField, onAddField }: Props) {
  const isBundle = proposal.workflow_type === "unbundle_classify_extract";
  const [collapsedDocuments, setCollapsedDocuments] = useState<Set<number>>(() => new Set());
  const [expandedFieldLists, setExpandedFieldLists] = useState<Set<number>>(() => new Set());
  const toggleIndex = (setter: Dispatch<SetStateAction<Set<number>>>, index: number) => {
    setter((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };
  return (
    <div className="grid gap-4">
      <p className="text-sm text-secondary text-pretty">
        Observed fields cite a matching label on a sample page. Suggested fields have no matching sample citation.
        Review the names and instructions before using this draft.
      </p>
      {proposal.documents.map((document, docIndex) => {
        const collapsed = collapsedDocuments.has(docIndex);
        const showAllFields = expandedFieldLists.has(docIndex);
        const visibleFields = showAllFields ? document.fields : document.fields.slice(0, initialFieldCount);
        return (
        <section key={`${document.key}-${docIndex}`} className="min-w-0 rounded-box border border-base-300 bg-base-100 p-3 sm:p-4" aria-label={`${document.name} proposed fields`}>
          <button type="button" className="flex min-h-11 w-full min-w-0 items-start gap-3 rounded-lg text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary"
            aria-expanded={!collapsed} aria-label={`${collapsed ? "Expand" : "Collapse"} ${document.name} fields`}
            onClick={() => toggleIndex(setCollapsedDocuments, docIndex)}>
            <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-base-200 text-secondary">
              <ChevronRightIcon className={`size-4 motion-safe:transition-transform motion-safe:duration-150 ${collapsed ? "" : "rotate-90"}`} aria-hidden="true" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-semibold text-balance">{document.name}</span>
                <span className="text-caption text-secondary tabular-nums">{document.fields.length} fields</span>
              </span>
              {isBundle && <span className="mt-1 line-clamp-2 block text-caption text-secondary text-pretty">Identify by: {document.distinguishing_evidence}</span>}
            </span>
          </button>
          {!collapsed && <div className="mt-3 border-t border-base-300 pt-3">
          {isBundle && (
            <details className="group/recognition rounded-box border border-base-300 bg-base-200 p-3">
              <summary className="flex cursor-pointer list-none items-center gap-2 font-medium [&::-webkit-details-marker]:hidden">
                <ChevronRightIcon className="size-4 shrink-0 text-secondary motion-safe:transition-transform motion-safe:duration-150 group-open/recognition:rotate-90" aria-hidden="true" />
                Document recognition
              </summary>
              <p className="mt-2 text-caption text-secondary text-pretty">
                These cues help identify this document and keep its continuation pages together.
              </p>
              <div className="mt-3 grid min-w-0 gap-3">
                <label className="grid gap-1 text-sm">Document name
                  <input className="input border-(--border-interactive) w-full" value={document.name}
                    onChange={(event) => onDocumentChange(docIndex, { name: event.target.value })} />
                </label>
                {([
                  ["Description", "description"],
                  ["Distinguishing evidence", "distinguishing_evidence"],
                  ["Continuation characteristics", "continuation_characteristics"],
                ] as const).map(([label, key]) => (
                  <label key={key} className="grid gap-1 text-sm">{label}
                    <textarea className="textarea border-(--border-interactive) w-full" rows={2}
                      value={document[key]} maxLength={300}
                      onChange={(event) => onDocumentChange(docIndex, { [key]: event.target.value })} />
                  </label>
                ))}
              </div>
            </details>
          )}
          <div className="mt-3 grid gap-2">
            {visibleFields.map((field, fieldIndex) => (
              <details key={fieldIndex} className="group min-w-0 rounded-box border border-base-300 bg-base-100 p-3">
                <summary className="grid cursor-pointer list-none grid-cols-[auto_minmax(0,1fr)] items-start gap-2 [&::-webkit-details-marker]:hidden">
                  <span className="grid size-7 shrink-0 place-items-center rounded-full bg-base-200 text-secondary">
                    <ChevronRightIcon className="size-4 motion-safe:transition-transform motion-safe:duration-150 group-open:rotate-90" aria-hidden="true" />
                  </span>
                  <span className="min-w-0">
                    <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                      <code className="font-mono text-sm font-medium [overflow-wrap:anywhere]">{field.name || "New field"}</code>
                      <span className="badge badge-ghost badge-sm">{field.type}</span>
                      {field.required && <span className="badge badge-outline badge-sm">Required</span>}
                      {field.guidance && <span className="text-caption text-secondary">Guidance added</span>}
                    </span>
                    <span className="mt-1 block text-caption text-secondary text-pretty">{field.description}</span>
                    <span className="mt-1 block text-caption text-secondary text-pretty">
                      {field.observed
                        ? `Observed · sample ${(field.sample_index ?? 0) + 1}, page/sheet ${field.unit} · ${field.source_label}`
                        : "Suggested · no matching sample citation"}
                    </span>
                  </span>
                </summary>
                <div className="mt-3 grid min-w-0 gap-3 border-t border-base-300 pt-3 md:grid-cols-2">
                  <label className="grid min-w-0 gap-1 text-sm">Field name
                    <input className="input border-(--border-interactive) w-full" value={field.name}
                      onChange={(event) => onFieldChange(docIndex, fieldIndex, { name: event.target.value })} />
                  </label>
                  <label className="grid min-w-0 gap-1 text-sm">Type
                    <select className="select border-(--border-interactive) w-full" value={field.type}
                      onChange={(event) => {
                        const type = event.target.value as ProposedField["type"];
                        onFieldChange(docIndex, fieldIndex, {
                          type, variable_rows: type === "list", enum_values: type === "enum" ? field.enum_values : [],
                        });
                      }}>
                      {fieldTypes.map((type) => <option key={type} value={type}>{type}</option>)}
                    </select>
                  </label>
                  <label className="grid min-w-0 gap-1 text-sm md:col-span-2">Description
                    <input className="input border-(--border-interactive) w-full" value={field.description}
                      maxLength={300} onChange={(event) => onFieldChange(docIndex, fieldIndex, { description: event.target.value })} />
                  </label>
                  <label className="grid min-w-0 gap-1 text-sm md:col-span-2">Extraction guidance <span className="text-caption text-secondary">Optional unless this is a list</span>
                    <textarea className="textarea border-(--border-interactive) w-full" rows={2} maxLength={500}
                      placeholder="For example, use original principal, not current balance."
                      value={field.guidance} onChange={(event) => onFieldChange(docIndex, fieldIndex, { guidance: event.target.value })} />
                  </label>
                  {field.type === "enum" && (
                    <label className="grid min-w-0 gap-1 text-sm md:col-span-2">Allowed choices <span className="text-caption text-secondary">One per line; use String if choices are open-ended</span>
                      <textarea className="textarea border-(--border-interactive) w-full" rows={3}
                        value={field.enum_values.join("\n")}
                        onChange={(event) => onFieldChange(docIndex, fieldIndex, { enum_values: event.target.value.split("\n") })} />
                    </label>
                  )}
                  <div className="flex flex-wrap items-center justify-between gap-3 md:col-span-2">
                    <label className="flex cursor-pointer items-center gap-2 text-sm">
                      <input type="checkbox" className="checkbox" checked={field.required}
                        onChange={(event) => onFieldChange(docIndex, fieldIndex, { required: event.target.checked })} />
                      Required when extracted
                    </label>
                    <button type="button" className="btn btn-ghost min-h-10" onClick={() => onRemoveField(docIndex, fieldIndex)}>Remove field</button>
                  </div>
                </div>
              </details>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {document.fields.length > initialFieldCount && (
              <button type="button" className="btn btn-ghost min-h-10"
                onClick={() => toggleIndex(setExpandedFieldLists, docIndex)}>
                {showAllFields ? `Show first ${initialFieldCount}` : `Show all ${document.fields.length} fields`}
              </button>
            )}
            <button type="button" className="btn btn-outline min-h-10" onClick={() => {
              setExpandedFieldLists((current) => new Set(current).add(docIndex));
              onAddField(docIndex);
            }}>Add field</button>
          </div>
          </div>}
        </section>
      );})}
    </div>
  );
}
