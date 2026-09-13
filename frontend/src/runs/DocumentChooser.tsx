import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { list } from "@/api/client";
import type { Dataset, Document } from "@/api/types";
import { ErrorNotice } from "@/components/ErrorNotice";
import { fmtBytes, StatusChip, TableSearch } from "@/components/ui";
import { useDebouncedSearch } from "@/hooks/useTableState";

const PAGE_SIZE = 25;

/** A draft selection: only Apply changes the run form; search and paging stay local. */
export function DocumentChooser({
  dataset,
  selectedIds,
  onApply,
  disabled = false,
}: {
  dataset?: Dataset;
  selectedIds: string[];
  onApply: (ids: string[]) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="btn btn-outline min-h-11 w-fit sm:min-h-10"
        disabled={disabled || !dataset}
        aria-haspopup="dialog"
        aria-controls={open ? id : undefined}
        onClick={() => setOpen(true)}
      >
        {selectedIds.length ? "Change selection" : "Choose documents"}
      </button>
      {open &&
        dataset &&
        createPortal(
          <DocumentChooserDialog
            id={id}
            dataset={dataset}
            selectedIds={selectedIds}
            onApply={onApply}
            onClose={() => {
              setOpen(false);
              trigger.current?.focus();
            }}
          />,
          document.body,
        )}
    </>
  );
}

function DocumentChooserDialog({
  id,
  dataset,
  selectedIds,
  onApply,
  onClose,
}: {
  id: string;
  dataset: Dataset;
  selectedIds: string[];
  onApply: (ids: string[]) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [selected, setSelected] = useState(() => new Set(selectedIds));
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useDebouncedSearch(query, (value) => {
    setQuery(value);
    setPage(1);
  });
  const documents = useQuery({
    queryKey: ["documents", dataset.id, "run-chooser", page, query],
    staleTime: 0, // Reopening must recheck eligibility, even within the app's cache window.
    queryFn: ({ signal }) =>
      list<Document>(
        "/documents/",
        {
          dataset: dataset.id,
          runnable: true,
          page,
          page_size: PAGE_SIZE,
          search: query,
          ordering: "created",
        },
        { signal },
      ),
  });
  useEffect(() => {
    dialog.current?.showModal();
    heading.current?.focus();
  }, []);
  const rows = documents.data?.results ?? [];
  const allVisibleSelected = rows.length > 0 && rows.every((doc) => selected.has(doc.id));
  const toggleVisible = () =>
    setSelected((current) => {
      const next = new Set(current);
      for (const doc of rows) {
        if (allVisibleSelected) next.delete(doc.id);
        else next.add(doc.id);
      }
      return next;
    });
  return (
    <dialog
      ref={dialog}
      id={id}
      className="modal p-4"
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-help`}
      onClose={onClose}
    >
      <div className="modal-box max-h-[calc(100dvh-2rem)] w-full max-w-2xl border border-base-300 p-4 sm:p-5 [&_.btn]:min-h-11 sm:[&_.btn]:min-h-10">
        <h2 ref={heading} id={`${id}-title`} tabIndex={-1} className="text-section-title">
          Choose documents
        </h2>
        <p id={`${id}-help`} className="mt-2 text-sm text-secondary [overflow-wrap:anywhere]">
          Select documents from {dataset.name}. Validated, processed and failed documents can be run.
        </p>
        <div className="mt-4">
          <TableSearch
            id={`${id}-search`}
            value={search}
            onChange={setSearch}
            placeholder="File name, hash, or document text"
            className="w-full [&_input]:min-h-11 sm:[&_input]:min-h-10"
          />
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm">
          <output className="tabular-nums">{selected.size.toLocaleString()} selected</output>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn btn-ghost min-h-11 px-2 sm:min-h-10"
              disabled={!rows.length || documents.isFetching || documents.isError}
              onClick={toggleVisible}
            >
              {allVisibleSelected ? "Deselect this page" : "Select this page"}
            </button>
            <button
              type="button"
              className="btn btn-ghost min-h-11 px-2 sm:min-h-10"
              disabled={!selected.size}
              onClick={() => setSelected(new Set())}
            >
              Clear selection
            </button>
          </div>
        </div>
        <div
          className="mt-2 max-h-[min(45dvh,24rem)] overflow-y-auto overscroll-contain rounded-box border border-base-300"
          aria-busy={documents.isFetching}
        >
          {documents.isError ? (
            <div className="p-4">
              <ErrorNotice
                message="Documents could not be loaded. Your selection is preserved."
                onRetry={() => void documents.refetch()}
              />
            </div>
          ) : documents.isPending ? (
            <output className="block p-4 text-sm text-secondary">Loading documents…</output>
          ) : !rows.length ? (
            <p className="p-4 text-sm text-secondary">
              {query
                ? "No eligible documents match your search."
                : "No eligible documents are available in this dataset."}
            </p>
          ) : (
            <ul className="list divide-y divide-base-300" aria-label="Eligible documents">
              {rows.map((doc) => (
                <li key={doc.id}>
                  <label
                    className={`flex min-h-12 cursor-pointer items-start gap-3 p-3 hover:bg-base-200 ${selected.has(doc.id) ? "bg-(--color-blue-soft)" : ""}`}
                  >
                    <input
                      type="checkbox"
                      className="checkbox checkbox-primary mt-1 shrink-0"
                      checked={selected.has(doc.id)}
                      aria-label={doc.original_filename}
                      onChange={(event) => {
                        const checked = event.target.checked;
                        setSelected((current) => {
                          const next = new Set(current);
                          if (checked) next.add(doc.id);
                          else next.delete(doc.id);
                          return next;
                        });
                      }}
                    />
                    <span className="grid min-w-0 flex-1 gap-1">
                      <span className="text-sm [overflow-wrap:anywhere]">{doc.original_filename}</span>
                      <span className="text-caption text-secondary">
                        {doc.file_format.toUpperCase()} · {fmtBytes(doc.size_bytes)}
                        {doc.page_count > 0 &&
                          ` · ${doc.page_count.toLocaleString()} page${doc.page_count === 1 ? "" : "s"}`}
                        {doc.sheet_count > 0 &&
                          ` · ${doc.sheet_count.toLocaleString()} sheet${doc.sheet_count === 1 ? "" : "s"}`}
                      </span>
                      <span>
                        <StatusChip status={doc.status} />
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
        <nav aria-label="Document pages" className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm">
          <p className="tabular-nums text-secondary">
            Page {page.toLocaleString()} of {Math.max(1, documents.data?.total_pages ?? page).toLocaleString()}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn btn-outline"
              disabled={page === 1 || documents.isFetching}
              onClick={() => setPage((value) => value - 1)}
            >
              Previous
            </button>
            <button
              type="button"
              className="btn btn-outline"
              disabled={
                !documents.data || page >= documents.data.total_pages || documents.isFetching || documents.isError
              }
              onClick={() => setPage((value) => value + 1)}
            >
              Next
            </button>
          </div>
        </nav>
        <form method="dialog" className="modal-action mt-4 flex-wrap" onSubmit={(event) => event.stopPropagation()}>
          <button type="button" className="btn btn-outline" onClick={() => dialog.current?.close()}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            disabled={!selected.size}
            onClick={(event) => {
              event.preventDefault();
              onApply([...selected]);
              dialog.current?.close();
            }}
          >
            Use {selected.size.toLocaleString()} document{selected.size === 1 ? "" : "s"}
          </button>
        </form>
      </div>
    </dialog>
  );
}
