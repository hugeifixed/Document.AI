/** Review and labeling workspace. Data orchestration stays here; document, labeling, and review UI
 * live in focused components so each workflow can evolve independently. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { announce } from "@/a11y/announce";
import { useSession } from "@/auth/Session";
import { ApiError, get, list, post } from "@/api/client";
import type { Document, ExtractedField, Label, LayoutUnit, Page, RunItem, Span } from "@/api/types";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { CorrectionDialog } from "@/components/CorrectionDialog";
import { ErrorNotice } from "@/components/ErrorNotice";
import { JourneyCue } from "@/components/JourneyCue";
import { ProcessingFailureNotice } from "@/components/ProcessingFailureNotice";
import { DocumentNavigation } from "@/components/review/DocumentNavigation";
import { ReviewDocumentPane } from "@/components/review/ReviewDocumentPane";
import { type EvidenceRequest, polygonBounds } from "@/components/review/evidence";
import { LabelPanel } from "@/components/review/LabelPanel";
import { type FieldAction, ReviewFieldPanel } from "@/components/review/ReviewFieldPanel";
import { Breadcrumbs, EmptyState } from "@/components/ui";
import { useGroundTruthSelection } from "@/groundTruth/selection";
import { useRunCollection } from "@/runs/lifecycle";
import { useDocumentWorkspaceScope } from "@/workspace/navigation";
import { authorizedQueryData } from "@/workspace/context";
import { fieldDisplayName, fieldDisplayValue, isCheckboxField } from "@/fieldPresentation";

type ReviewMutation = {
  id: string;
  action: FieldAction;
  value?: string;
  reason: string;
};

export function ReviewWorkspace({ mode }: { mode: "inspect" | "review" | "label" }) {
  const { documentId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const qc = useQueryClient();
  const { user } = useSession();
  const runId = searchParams.get("run");
  const runItems = useQuery({
    queryKey: ["run-items-for-document", documentId],
    queryFn: ({ signal }) =>
      list<RunItem>("/run-items/", { page_size: 200, ordering: "-modified", document: documentId }, { signal }),
    enabled: !!documentId,
  });
  const activeRun = runId ?? runItems.data?.results[0]?.run;
  const doc = useQuery({
    queryKey: ["document", documentId, activeRun ?? null],
    queryFn: ({ signal }) =>
      get<Document>("/documents/" + documentId + "/", activeRun ? { run: activeRun } : undefined, { signal }),
  });
  useDocumentWorkspaceScope(doc.data?.id === documentId ? authorizedQueryData(doc) : undefined);
  const runs = useRunCollection({ purpose: "review", datasetId: doc.data?.dataset, documentId });
  const [originalScope, setOriginalScope] = useState<string | null>(null);
  const sourceScope = `${documentId}:${activeRun ?? ""}`;
  const viewingOriginal = originalScope === sourceScope && doc.data?.processing_source?.is_original === false;
  const processingFormat = doc.data?.processing_source?.file_format ?? doc.data?.file_format;
  const activeRunItem = runItems.data?.results.find((item) => item.run === activeRun);
  const fields = useQuery({
    queryKey: ["fields", documentId, activeRun],
    enabled: !!activeRun,
    queryFn: ({ signal }) =>
      list<ExtractedField>(
        "/fields/",
        { document: documentId, run: activeRun, page_size: 200, ordering: "name" },
        { signal },
      ),
  });
  const pendingQueue = useQuery({
    queryKey: ["fields", "guided-review", doc.data?.dataset, activeRun],
    enabled: mode === "review" && !!doc.data?.dataset && !!activeRun,
    queryFn: ({ signal }) =>
      list<ExtractedField>(
        "/fields/",
        {
          dataset: doc.data?.dataset,
          run: activeRun,
          review_status: "needs_review",
          page_size: 200,
        },
        { signal },
      ),
  });
  const labels = useQuery({
    queryKey: ["labels", documentId, activeRun ?? null],
    enabled: !!runId || runItems.isFetched,
    queryFn: ({ signal }) =>
      list<Label>("/labels/", { document: documentId, run: activeRun, page_size: 200 }, { signal }),
  });
  const [unit, setUnit] = useState(0);
  const selectedField = searchParams.get("field");
  const [selectionAttempt, setSelectionAttempt] = useState(0);
  const [evidenceRequest, setEvidenceRequest] = useState<EvidenceRequest | null>(null);
  const handledSelection = useRef<string | null>(null);
  const evidenceSequence = useRef(0);
  const initializedReviewScope = useRef<string | null>(null);
  const layout = useQuery({
    queryKey: ["unit", documentId, activeRun ?? null, doc.data?.processing_source?.layout_artifact ?? null, unit],
    queryFn: ({ signal }) =>
      get<LayoutUnit>("/documents/" + documentId + "/units/" + unit + "/", activeRun ? { run: activeRun } : undefined, {
        signal,
      }),
    enabled: !!doc.data && (doc.data.units?.length ?? 0) > 0,
  });
  const [scale, setScale] = useState(1.1);
  const [correction, setCorrection] = useState<ExtractedField | null>(null);
  const [reviewConfirmation, setReviewConfirmation] = useState<{
    field: ExtractedField;
    action: "reject" | "promote";
  } | null>(null);
  const [reviewPlan, setReviewPlan] = useState<{ key: string; ids: string[] } | null>(null);
  const [reviewComplete, setReviewComplete] = useState(false);
  const groundTruth = useGroundTruthSelection({
    documentId: documentId ?? "",
    unit,
    fileFormat: processingFormat,
    runId: activeRun,
    representationKey: `${doc.data?.processing_source?.layout_artifact ?? ""}:${viewingOriginal ? "original" : "processed"}`,
    hasTextLayer: layout.data?.has_text_layer,
  });
  const canSee =
    !!user && user.roles.some((role) => ["docai_operators", "docai_reviewers", "docai_approvers"].includes(role));
  const canReview = !!user?.roles.includes("docai_reviewers");
  const canApprove = !!user?.roles.includes("docai_approvers");
  const spansOnUnit: Span[] = useMemo(() => {
    const fromFields = (fields.data?.results ?? []).flatMap((field) =>
      field.spans
        .filter((span) => span.unit_index === unit)
        .map((span) => ({
          ...span,
          text:
            fieldDisplayName(field.name) +
            ": " +
            (fieldDisplayValue(field, field.reviewed_value ?? field.raw_value) ?? ""),
          id: field.id,
        })),
    );
    const fromLabels = (labels.data?.results ?? []).flatMap((label) =>
      label.spans
        .filter((span) => span.unit_index === unit)
        .map((span) => ({ ...span, text: "label " + fieldDisplayName(label.field_name), id: "label-" + label.id })),
    );
    return [...fromFields, ...fromLabels];
  }, [fields.data, labels.data, unit]);
  const schemaFields = useMemo(
    () => Array.from(new Set((fields.data?.results ?? []).map((field) => field.name))),
    [fields.data],
  );

  useEffect(() => {
    setUnit(0);
    setCorrection(null);
    setReviewConfirmation(null);
    setReviewPlan(null);
    setReviewComplete(false);
  }, [documentId, activeRun]);

  const selectField = useCallback(
    (fieldId: string) => {
      // A changed URL already triggers a request; only repeated activation needs a nonce.
      if (fieldId === selectedField) setSelectionAttempt((attempt) => attempt + 1);
      const next = new URLSearchParams(searchParams);
      next.set("field", fieldId);
      setSearchParams(next, { replace: true });
    },
    [searchParams, selectedField, setSearchParams],
  );
  const selectRun = (nextRun: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("run", nextRun);
    next.delete("field");
    setUnit(0);
    setSearchParams(next, { replace: true });
  };
  const clearFieldSelection = () => {
    initializedReviewScope.current = sourceScope;
    setEvidenceRequest(null);
    const next = new URLSearchParams(searchParams);
    next.delete("field");
    setSearchParams(next, { replace: true });
    announce("Field selection cleared.");
  };
  useEffect(() => {
    const selectionKey = JSON.stringify([sourceScope, selectedField, selectionAttempt]);
    if (handledSelection.current === selectionKey) return;
    if (!selectedField) {
      handledSelection.current = selectionKey;
      setEvidenceRequest(null);
      return;
    }
    if (!fields.data || !doc.data) return;
    const field = fields.data?.results.find((candidate) => candidate.id === selectedField);
    if (!field) return;
    // Consume this activation once; a query refetch must not undo manual navigation.
    handledSelection.current = selectionKey;
    const savedSpans = field.spans.filter((span) => doc.data.units?.some((page) => page.index === span.unit_index));
    const evidence = savedSpans.find((span) => polygonBounds(span.polygon)) ?? savedSpans[0];
    if (evidence) {
      setUnit(evidence.unit_index);
      setOriginalScope(null);
    }
    setEvidenceRequest({
      id: ++evidenceSequence.current,
      scope: sourceScope,
      fieldId: field.id,
      fieldName: fieldDisplayName(field.name, { includePage: !evidence }),
      unit: evidence?.unit_index ?? null,
      switchedSource: !!evidence && viewingOriginal,
    });
  }, [doc.data, fields.data, selectedField, selectionAttempt, sourceScope, viewingOriginal]);
  const reviewKey = `${documentId ?? ""}:${activeRun ?? ""}`;
  useEffect(() => {
    if (mode !== "review" || !fields.data || reviewPlan?.key === reviewKey) return;
    setReviewPlan({
      key: reviewKey,
      ids: fields.data.results.filter((field) => field.review_status === "needs_review").map((field) => field.id),
    });
  }, [fields.data, mode, reviewKey, reviewPlan?.key]);
  useEffect(() => {
    if (mode !== "review" || !fields.data || initializedReviewScope.current === sourceScope) return;
    // Initialize once per document/run; clearing or refetching must not select it again.
    if (selectedField) {
      initializedReviewScope.current = sourceScope;
      return;
    }
    const first = fields.data.results.find((field) => field.review_status === "needs_review");
    if (first) {
      initializedReviewScope.current = sourceScope;
      selectField(first.id);
    }
  }, [fields.data, mode, selectField, selectedField, sourceScope]);

  const review = useMutation<ExtractedField | Label, ApiError, ReviewMutation>({
    mutationFn: ({ id, action, value, reason }: ReviewMutation) =>
      action === "promote"
        ? post("/fields/" + id + "/promote/", { reason })
        : post("/fields/" + id + "/review/", { action, ...(value !== undefined ? { value } : {}), reason }),
    onSuccess: (updated, values) => {
      setCorrection(null);
      setReviewConfirmation(null);
      const labels: Record<FieldAction, string> = {
        accept: "accepted",
        correct: "corrected",
        mark_absent: "marked absent",
        reject: "rejected",
        promote: "promoted to ground truth",
      };
      toast.success("Field " + labels[values.action]);
      if (values.action !== "promote") {
        const updatedField = updated as ExtractedField;
        const fieldQueryKey = ["fields", documentId, activeRun];
        const currentFields =
          fields.data?.results.map((field) => (field.id === updatedField.id ? updatedField : field)) ?? [];
        qc.setQueryData<Page<ExtractedField>>(fieldQueryKey, (current) =>
          current
            ? {
                ...current,
                results: current.results.map((field) => (field.id === updatedField.id ? updatedField : field)),
              }
            : current,
        );
        const remaining = (reviewPlan?.ids ?? [])
          .map((id) => currentFields.find((field) => field.id === id))
          .filter((field): field is ExtractedField => !!field && field.review_status === "needs_review");
        if (remaining.length > 0) selectField(remaining[0].id);
        if (reviewPlan && remaining.length === 0) setReviewComplete(true);
      }
      void qc.invalidateQueries({ queryKey: ["fields"] });
      void qc.invalidateQueries({ queryKey: ["labels", documentId] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error: ApiError) => toast.error(error.message + " (" + error.code + ")"),
  });

  const actOnField = (field: ExtractedField, action: Exclude<FieldAction, "correct">) => {
    if (action === "reject" || action === "promote") {
      setReviewConfirmation({ field, action });
      return;
    }
    review.mutate({
      id: field.id,
      action,
      reason: action === "accept" ? "Accepted in review workspace" : "Marked absent in review workspace",
    });
  };

  if (doc.error) return <ErrorNotice message={doc.error.message} onRetry={() => void doc.refetch()} />;
  if (!doc.data || (!runId && runItems.isPending)) return <output className="block">Loading…</output>;
  if (mode === "label" && !canReview) {
    return (
      <div>
        <Breadcrumbs items={[{ label: "Ground truth", to: "/labeling" }, { label: doc.data.original_filename }]} />
        <EmptyState
          text="Creating ground truth requires the reviewer role."
          action={
            <Link className="btn btn-outline btn-sm" to="/results">
              View extracted results
            </Link>
          }
        />
      </div>
    );
  }
  if (!canSee) {
    return (
      <div>
        <Breadcrumbs items={[{ label: "Extracted results", to: "/results" }, { label: doc.data.original_filename }]} />
        <EmptyState
          text="Viewing document content requires the operator, reviewer, or approver role."
          action={
            <Link className="btn btn-outline btn-sm" to="/results">
              Back to extracted results
            </Link>
          }
        />
      </div>
    );
  }

  const currentRun = runs.data?.results.find((run) => run.id === activeRun);
  const reviewPending = fields.data?.results.filter((field) => field.review_status === "needs_review").length ?? 0;
  const reviewTotal = reviewPlan?.ids.length ?? 0;
  const reviewDone = Math.max(0, reviewTotal - reviewPending);
  const nextDocumentField = pendingQueue.data?.results.find((field) => field.document !== documentId);
  const origin = searchParams.get("from");
  const rootBreadcrumb =
    mode === "label"
      ? { label: "Ground truth", to: "/labeling" }
      : mode === "review"
        ? origin === "document"
          ? {
              label: "Document details",
              to: `/documents/${documentId}?${new URLSearchParams({ ...(activeRun ? { run: activeRun } : {}), from: "datasets" }).toString()}`,
            }
          : { label: "Review queue", to: activeRun ? `/review?run=${activeRun}` : "/review" }
        : origin === "run" && activeRun
          ? { label: currentRun?.name || "Run", to: `/runs/${activeRun}` }
          : origin === "results"
            ? { label: "Extracted results", to: activeRun ? `/results?run=${activeRun}` : "/results" }
            : { label: "Datasets & documents", to: "/datasets" };
  return (
    <div>
      <Breadcrumbs items={[rootBreadcrumb, { label: doc.data.original_filename }]} />
      {mode === "review" && reviewTotal > 0 && !reviewComplete && (
        <div className="mb-4 rounded-box border border-base-300 bg-base-100 px-4 py-3 text-sm">
          <strong className="font-semibold tabular-nums">
            {reviewDone} of {reviewTotal} flagged fields reviewed
          </strong>
          <span className="ml-2 text-secondary">The next unresolved field is selected automatically.</span>
        </div>
      )}
      {mode === "review" && reviewComplete && (
        <JourneyCue
          className="mb-4"
          action={
            nextDocumentField
              ? {
                  title: "This document's review is complete",
                  description: "Continue with the next document that contains a flagged result from this run.",
                  label: "Review next document",
                  to: `/review/${nextDocumentField.document}?run=${activeRun}&field=${nextDocumentField.id}&from=review`,
                }
              : {
                  title: "Review is complete for this run",
                  description: "Inspect the resolved values before evaluating or exporting the stored results.",
                  label: "View extracted results",
                  to: `/results?run=${activeRun}`,
                }
          }
        />
      )}
      {activeRunItem?.status === "failed" && <ProcessingFailureNotice item={activeRunItem} />}
      {(runItems.error || runs.error || fields.error || labels.error) && (
        <div className="mb-4 grid gap-3">
          {runItems.error && (
            <ErrorNotice message="The processing status could not be loaded." onRetry={() => void runItems.refetch()} />
          )}
          {runs.error && (
            <ErrorNotice message="The available runs could not be loaded." onRetry={() => void runs.refetch()} />
          )}
          {fields.error && (
            <ErrorNotice message="The extracted fields could not be loaded." onRetry={() => void fields.refetch()} />
          )}
          {labels.error && (
            <ErrorNotice message="The ground-truth labels could not be loaded." onRetry={() => void labels.refetch()} />
          )}
        </div>
      )}
      {mode === "inspect" && (runItems.isSuccess || !!runId) && doc.data.navigation && (
        <DocumentNavigation navigation={doc.data.navigation} searchParams={searchParams} />
      )}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <ReviewDocumentPane
          key={sourceScope}
          document={doc.data}
          viewingOriginal={viewingOriginal}
          onSourceChange={(original) => {
            setEvidenceRequest(null);
            setOriginalScope(original ? sourceScope : null);
          }}
          unit={unit}
          onUnitChange={(nextUnit) => {
            setEvidenceRequest(null);
            setUnit(nextUnit);
          }}
          scale={scale}
          onScaleChange={setScale}
          activeRun={activeRun}
          runs={runs.data?.results ?? []}
          onRunChange={selectRun}
          layout={viewingOriginal ? undefined : layout.data}
          layoutError={layout.isError}
          onRetryLayout={() => void layout.refetch()}
          spans={viewingOriginal ? [] : spansOnUnit}
          selectedField={selectedField}
          evidenceRequest={
            evidenceRequest?.scope === sourceScope && evidenceRequest.fieldId === selectedField ? evidenceRequest : null
          }
          groundTruth={mode === "label" && !viewingOriginal && layout.data ? groundTruth : undefined}
        />
        <aside
          aria-label={mode === "label" ? "Ground truth" : mode === "review" ? "Fields" : "Extracted fields"}
          className="min-w-0 rounded-box border border-base-300 bg-base-100 p-4 sm:p-5"
        >
          {mode === "label" ? (
            viewingOriginal ? (
              <p className="text-sm text-secondary">
                Switch to the processing source to select evidence and create labels aligned with this result version.
              </p>
            ) : (
              <LabelPanel
                key={`${sourceScope}:${doc.data.processing_source?.layout_artifact ?? ""}`}
                selection={groundTruth}
                schemaFields={schemaFields}
                labels={labels.data?.results ?? []}
                disabled={!layout.data}
              />
            )
          ) : (
            <ReviewFieldPanel
              fields={fields.data?.results ?? []}
              selectedField={selectedField}
              activeRun={activeRun}
              documentFailed={activeRunItem?.status === "failed"}
              canReview={mode === "review" && canReview}
              canApprove={mode === "review" && canApprove}
              pendingAction={review.isPending ? review.variables : undefined}
              onSelect={selectField}
              onClearSelection={clearFieldSelection}
              onAction={actOnField}
              onCorrect={setCorrection}
            />
          )}
        </aside>
      </div>
      {correction && (
        <CorrectionDialog
          fieldName={fieldDisplayName(correction.name)}
          fieldType={correction.field_type}
          initialValue={correction.reviewed_value ?? correction.raw_value ?? ""}
          valueHelp={
            isCheckboxField(correction)
              ? "Stored checkbox states use selected (Checked) or unselected (Unchecked)."
              : undefined
          }
          pending={review.isPending && review.variables?.action === "correct"}
          onClose={() => setCorrection(null)}
          onConfirm={(value) =>
            review.mutate({
              id: correction.id,
              action: "correct",
              value,
              reason: "Corrected in review workspace",
            })
          }
        />
      )}
      <ConfirmDialog
        open={!!reviewConfirmation}
        pending={review.isPending}
        title={reviewConfirmation?.action === "promote" ? "Promote field to ground truth" : "Reject field"}
        confirmLabel={reviewConfirmation?.action === "promote" ? "Promote" : "Reject"}
        destructive={reviewConfirmation?.action === "reject"}
        reasonLabel="Reason"
        reasonRequired
        reasonHelp="This reason is recorded in the field review history."
        summary={
          reviewConfirmation && (
            <p>
              {reviewConfirmation.action === "promote" ? (
                <>
                  Promote <strong>{fieldDisplayName(reviewConfirmation.field.name)}</strong> as ground truth for this
                  document.
                </>
              ) : (
                <>
                  Reject <strong>{fieldDisplayName(reviewConfirmation.field.name)}</strong> and keep the original
                  prediction in its history.
                </>
              )}
            </p>
          )
        }
        onClose={() => setReviewConfirmation(null)}
        onConfirm={(reason) => {
          if (reviewConfirmation)
            review.mutate({
              id: reviewConfirmation.field.id,
              action: reviewConfirmation.action,
              reason,
            });
        }}
      />
    </div>
  );
}

export function ReviewPage() {
  return <ReviewWorkspace mode="review" />;
}

export function DocumentPage() {
  return <ReviewWorkspace mode="inspect" />;
}

export function LabelPage() {
  return <ReviewWorkspace mode="label" />;
}
