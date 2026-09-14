import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { RowSelectionState } from "@tanstack/react-table";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, list, post, tableParams } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { CategoryDefinition, Classification, ExtractedField } from "@/api/types";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable } from "@/components/DataTable";
import { FileNameLink } from "@/components/FileNameLink";
import { ReclassificationDialog } from "@/components/ReclassificationDialog";
import { ConfidenceCue, PageHeader, StatusChip, TableSearch } from "@/components/ui";
import { listSummary } from "@/listValues";
import { useDebouncedSearch, useTableState } from "@/hooks/useTableState";
import { useWorkingContext } from "@/workspace/context";
import { fieldDisplayName, fieldDisplayValue } from "@/fieldPresentation";

function fieldReviewPath(field: ExtractedField) {
  return `/review/${field.document}?run=${field.run}&field=${field.id}&from=review`;
}

function QueueFieldValue({ field }: { field: ExtractedField }) {
  const value = field.field_type === "list" ? listSummary(field.raw_value) : fieldDisplayValue(field, field.raw_value);
  return (
    <Link
      to={fieldReviewPath(field)}
      className={`link link-hover block max-w-64 font-mono leading-5 ${
        field.field_type === "list" ? "whitespace-nowrap" : "line-clamp-2 whitespace-normal [overflow-wrap:anywhere]"
      }`}
    >
      {value ?? <em>Not found</em>}
    </Link>
  );
}

export function ReviewQueue() {
  const { user } = useSession();
  const canReview = !!user?.roles.includes("docai_reviewers");
  const qc = useQueryClient();
  const { projectId, datasetId } = useWorkingContext();
  const { state, update } = useTableState(["name", "run", "kind"]);
  const [classificationCorrection, setClassificationCorrection] = useState<Classification | null>(null);
  const [search, setSearch] = useDebouncedSearch(state.q, (value) => update({ q: value }));
  const requestedKind = state.filters.kind === "classifications" ? "classifications" : "fields";
  const sharedFilters: Record<string, string> = state.filters.run ? { run: state.filters.run } : {};
  const fieldState = {
    ...state,
    filters: sharedFilters,
    sort: !state.sort || ["name", "score", "validation_status"].includes(state.sort) ? state.sort : undefined,
  };
  const classificationState = {
    ...state,
    filters: sharedFilters,
    sort: !state.sort || ["category", "score", "method"].includes(state.sort) ? state.sort : undefined,
  };
  const fields = useQuery({
    queryKey: ["fields", "queue", projectId, datasetId, state],
    queryFn: ({ signal }) =>
      list<ExtractedField>(
        "/fields/",
        {
          ...tableParams(fieldState),
          review_status: "needs_review",
          ...(projectId ? { project: projectId } : {}),
          ...(datasetId ? { dataset: datasetId } : {}),
          ...(state.filters.run ? { run: state.filters.run } : {}),
        },
        { signal },
      ),
  });
  const classifications = useQuery({
    queryKey: ["classifications", "queue", projectId, datasetId, state],
    queryFn: ({ signal }) =>
      list<Classification>(
        "/classifications/",
        {
          ...tableParams(classificationState),
          review_status: "needs_review",
          ...(projectId ? { project: projectId } : {}),
          ...(datasetId ? { dataset: datasetId } : {}),
          ...(state.filters.run ? { run: state.filters.run } : {}),
        },
        { signal },
      ),
  });
  const categories = useQuery({
    queryKey: ["categories", projectId, "review-options"],
    enabled: canReview && !!projectId && !!classificationCorrection,
    queryFn: ({ signal }) =>
      list<CategoryDefinition>("/categories/", { project: projectId, page_size: 200 }, { signal }),
  });
  const categorySuggestions = useMemo(
    () => Array.from(new Set((categories.data?.results ?? []).map((category) => category.key))).sort(),
    [categories.data],
  );
  const activeKind =
    !state.filters.kind && fields.data?.count === 0 && (classifications.data?.count ?? 0) > 0
      ? "classifications"
      : requestedKind;
  const [sel, setSel] = useState<RowSelectionState>({});
  const [confirm, setConfirm] = useState<"accept" | "reject" | null>(null);
  const selectionScope = `${projectId ?? ""}:${datasetId ?? ""}:${state.page}:${state.pageSize}:${state.sort ?? ""}:${state.desc ?? false}:${state.q ?? ""}:${JSON.stringify(state.filters)}`;
  useEffect(() => {
    setSel({});
    setConfirm(null);
  }, [selectionScope]);
  const ids = (fields.data?.results ?? []).map((field) => field.id).filter((id) => sel[id]);
  const bulk = useMutation({
    mutationFn: ({ action, reason }: { action: "accept" | "reject"; reason: string }) =>
      post<{ applied: string[]; skipped: unknown[] }>("/fields/bulk-review/", {
        field_ids: ids,
        action,
        confirm_count: ids.length,
        reason,
      }),
    onSuccess: (r) => {
      toast.success(`${r.applied.length} field(s) updated`);
      setSel({});
      setConfirm(null);
      qc.invalidateQueries({ queryKey: ["fields"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e: ApiError) => toast.error(`${e.message} (${e.code})`),
  });
  const classificationReview = useMutation({
    mutationFn: ({
      classification,
      action,
      category,
      reason,
    }: {
      classification: Classification;
      action: "accept" | "reclassify";
      category?: string;
      reason?: string;
    }) =>
      action === "accept"
        ? post<Classification>(`/classifications/${classification.id}/accept/`, {
            reason: "Accepted in review queue",
          })
        : post<Classification>(`/classifications/${classification.id}/reclassify/`, { category, reason }),
    onSuccess: (_, values) => {
      toast.success(values.action === "accept" ? "Classification accepted" : "Classification corrected");
      setClassificationCorrection(null);
      void qc.invalidateQueries({ queryKey: ["classifications"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e: ApiError) => toast.error(`${e.message} (${e.code})`),
  });
  return (
    <div>
      <PageHeader
        title="Review queue"
        action={
          canReview &&
          activeKind === "fields" &&
          ids.length > 0 && (
            <div className="flex gap-2">
              <button className="btn btn-sm btn-outline" disabled={bulk.isPending} onClick={() => setConfirm("accept")}>
                Accept {ids.length}
              </button>
              <button
                className="btn btn-sm btn-outline btn-error"
                disabled={bulk.isPending}
                onClick={() => setConfirm("reject")}
              >
                Reject {ids.length}
              </button>
            </div>
          )
        }
      >
        Extracted fields and document classifications routed to a human because confidence, grounding, validation, or
        evidence needs a decision.
      </PageHeader>
      {!canReview && (
        <output className="alert mb-6">This is a read-only view. Resolving results requires the reviewer role.</output>
      )}
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <TableSearch
          id="review-queue-search"
          className="w-full sm:max-w-sm"
          value={search}
          onChange={setSearch}
          placeholder={activeKind === "fields" ? "Document, field, or value" : "Document or category"}
        />
        <div aria-label="Review result type" className="tabs tabs-box bg-base-200">
          {(["fields", "classifications"] as const).map((kind) => (
            <button
              key={kind}
              type="button"
              aria-pressed={activeKind === kind}
              className={`tab gap-2 ${activeKind === kind ? "tab-active text-base-content" : "text-secondary"}`}
              onClick={() => {
                setSel({});
                setConfirm(null);
                update({ page: 1, sort: undefined, desc: undefined, filters: { kind } });
              }}
            >
              {kind === "fields" ? "Fields" : "Classifications"}
              <span className="badge badge-sm badge-ghost tabular-nums">
                {(kind === "fields" ? fields.data?.count : classifications.data?.count)?.toLocaleString() ?? "…"}
              </span>
            </button>
          ))}
        </div>
      </div>
      {activeKind === "fields" ? (
        <DataTable<ExtractedField>
          caption="Fields needing review"
          data={fields.data}
          isLoading={fields.isLoading}
          isFetching={fields.isFetching}
          error={fields.error as Error}
          onRetry={() => fields.refetch()}
          state={fieldState}
          update={update}
          getRowId={(r) => r.id}
          selection={canReview ? sel : undefined}
          onSelectionChange={canReview ? setSel : undefined}
          rowName={(r) => `${r.document_name} ${fieldDisplayName(r.name)}`}
          emptyText={
            <span>
              No extracted fields need review in this context.{" "}
              {(classifications.data?.count ?? 0) > 0 ? (
                <button
                  type="button"
                  className="link link-primary"
                  onClick={() => update({ page: 1, sort: undefined, filters: { kind: "classifications" } })}
                >
                  Review classifications.
                </button>
              ) : (
                state.filters.run && (
                  <Link className="link link-primary" to={`/results?run=${state.filters.run}`}>
                    View the resolved results.
                  </Link>
                )
              )}
            </span>
          }
          columns={[
            {
              id: "document__original_filename",
              header: "Document",
              enableSorting: false,
              accessorKey: "document_name",
              cell: (c) => <FileNameLink name={c.getValue<string>()} to={fieldReviewPath(c.row.original)} />,
            },
            { id: "name", header: "Field", accessorKey: "name", cell: (c) => fieldDisplayName(c.row.original.name) },
            {
              id: "raw_value",
              header: "Value",
              enableSorting: false,
              accessorKey: "raw_value",
              cell: (c) => <QueueFieldValue field={c.row.original} />,
            },
            {
              id: "score",
              header: "Model confidence",
              accessorKey: "score",
              cell: (c) => (
                <ConfidenceCue score={c.getValue<number | null>()} label={fieldDisplayName(c.row.original.name)} />
              ),
            },
            {
              id: "validation_status",
              header: "Validation",
              accessorKey: "validation_status",
              cell: (c) => (
                <>
                  <StatusChip status={c.getValue<string>()} />
                  {c.row.original.validation_messages[0] && (
                    <span className="ml-2 text-caption">{c.row.original.validation_messages[0]}</span>
                  )}
                </>
              ),
            },
            {
              id: "grounded",
              header: "Grounded",
              enableSorting: false,
              accessorKey: "grounded",
              cell: (c) => (c.getValue<boolean>() ? "yes" : "no"),
            },
          ]}
        />
      ) : (
        <DataTable<Classification>
          caption="Classifications needing review"
          data={classifications.data}
          isLoading={classifications.isLoading}
          isFetching={classifications.isFetching}
          error={classifications.error as Error}
          onRetry={() => classifications.refetch()}
          state={classificationState}
          update={update}
          getRowId={(r) => r.id}
          emptyText={
            <span>
              No document classifications need review in this context.{" "}
              {(fields.data?.count ?? 0) > 0 ? (
                <button
                  type="button"
                  className="link link-primary"
                  onClick={() => update({ page: 1, sort: undefined, filters: { kind: "fields" } })}
                >
                  Review extracted fields.
                </button>
              ) : (
                state.filters.run && (
                  <Link className="link link-primary" to={`/results?run=${state.filters.run}`}>
                    View the resolved results.
                  </Link>
                )
              )}
            </span>
          }
          columns={[
            {
              id: "document__original_filename",
              header: "Document",
              enableSorting: false,
              accessorKey: "document_name",
              cell: (c) => (
                <FileNameLink
                  name={c.getValue<string>()}
                  to={`/documents/${c.row.original.document}?run=${c.row.original.run}&from=review`}
                />
              ),
            },
            {
              id: "category",
              header: "Predicted category",
              accessorKey: "category",
              cell: (c) => <span className="font-mono text-sm">{c.getValue<string>()}</span>,
            },
            {
              id: "score",
              header: "Model confidence",
              accessorKey: "score",
              cell: (c) => <ConfidenceCue score={c.getValue<number | null>()} label="classification" />,
            },
            { id: "method", header: "Method", accessorKey: "method" },
            {
              id: "actions",
              header: "Actions",
              enableSorting: false,
              cell: (c) =>
                canReview ? (
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="btn btn-xs btn-outline"
                      disabled={classificationReview.isPending}
                      onClick={() => classificationReview.mutate({ classification: c.row.original, action: "accept" })}
                    >
                      Accept
                    </button>
                    <button
                      type="button"
                      className="btn btn-xs btn-primary"
                      disabled={classificationReview.isPending}
                      onClick={() => setClassificationCorrection(c.row.original)}
                    >
                      Correct
                    </button>
                  </div>
                ) : (
                  <span className="text-caption text-secondary">Read only</span>
                ),
            },
          ]}
        />
      )}
      <ConfirmDialog
        pending={bulk.isPending}
        open={canReview && !!confirm}
        title={`${confirm === "accept" ? "Accept" : "Reject"} ${ids.length} field(s)`}
        confirmLabel={confirm === "accept" ? "Accept all" : "Reject all"}
        typed={String(ids.length)}
        destructive={confirm === "reject"}
        reasonLabel={confirm === "reject" ? "Reason" : "Review note (optional)"}
        reasonRequired={confirm === "reject"}
        reasonHelp="This note is recorded with each selected field."
        onClose={() => setConfirm(null)}
        onConfirm={(reason) => {
          if (confirm) bulk.mutate({ action: confirm, reason });
        }}
        summary={
          <p>
            This applies to {ids.length} selected field(s). Original predictions are preserved; each action is recorded
            with your name. Type the count to confirm.
          </p>
        }
      />
      {classificationCorrection && (
        <ReclassificationDialog
          documentName={classificationCorrection.document_name}
          initialCategory={classificationCorrection.category}
          suggestions={categorySuggestions}
          pending={classificationReview.isPending}
          onClose={() => setClassificationCorrection(null)}
          onConfirm={(category, reason) =>
            classificationReview.mutate({
              classification: classificationCorrection,
              action: "reclassify",
              category,
              reason,
            })
          }
        />
      )}
    </div>
  );
}
