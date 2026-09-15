import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { ApiError, list, post, tableParams } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { Dataset, Document, Page } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { FileNameLink } from "@/components/FileNameLink";
import { JourneyCue } from "@/components/JourneyCue";
import { UploadDropzone } from "@/components/UploadDropzone";
import {
  AsyncButton,
  Card,
  EmptyState,
  Field,
  fmtBytes,
  fmtDate,
  PageHeader,
  StatusChip,
  TableSearch,
} from "@/components/ui";
import { useDebouncedSearch, useTableState } from "@/hooks/useTableState";
import type { UploadSummary } from "@/hooks/useUploadQueue";
import { nextDatasetAction, useJourneyDashboard } from "@/journey/guidance";
import { useWorkingContext } from "@/workspace/context";

const schema = z.object({
  name: z.string().min(1, "Name is required").max(120),
  split: z.enum(["train", "dev", "validation", "test", "unsplit"]),
  is_production: z.boolean(),
});
type Form = z.infer<typeof schema>;

const SPLIT_OPTIONS = [
  { value: "train", label: "Training — tune prompts and configurations" },
  { value: "dev", label: "Development — everyday iteration" },
  { value: "validation", label: "Validation — check changes during development" },
  { value: "test", label: "Test — final unbiased evaluation" },
  { value: "unsplit", label: "Unassigned — decide later" },
] as const;

const SPLIT_PURPOSE: Record<Dataset["split"], string> = {
  train: "Prompt and configuration tuning",
  dev: "Everyday iteration",
  validation: "Pre-release validation",
  test: "Final unbiased evaluation",
  unsplit: "Not assigned",
};

function addCreatedDataset(current: Page<Dataset> | undefined, dataset: Dataset): Page<Dataset> {
  const pageSize = current?.page_size ?? 200;
  const alreadyPresent = current?.results.some((candidate) => candidate.id === dataset.id) ?? false;
  const count = (current?.count ?? 0) + (alreadyPresent ? 0 : 1);
  const results = [...(current?.results.filter((candidate) => candidate.id !== dataset.id) ?? []), dataset]
    .sort((left, right) => left.name.localeCompare(right.name) || left.id.localeCompare(right.id))
    .slice(0, pageSize);

  return {
    count,
    page: current?.page ?? 1,
    page_size: pageSize,
    total_pages: Math.max(1, Math.ceil(count / pageSize)),
    results,
  };
}

export function Datasets() {
  const { user } = useSession();
  const canOperate = !!user?.roles.includes("docai_operators");
  const { projectId, datasetId, selectDatasetForProject } = useWorkingContext();
  const [lastUpload, setLastUpload] = useState<UploadSummary | null>(null);
  const qc = useQueryClient();
  const { state, update } = useTableState(["status", "file_format"]);
  const [search, setSearch] = useDebouncedSearch(state.q, (value) => update({ q: value }));
  const docs = useQuery({
    queryKey: ["documents", datasetId, state],
    enabled: !!datasetId,
    queryFn: ({ signal }) => list<Document>("/documents/", { ...tableParams(state), dataset: datasetId }, { signal }),
  });
  const datasets = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: ({ signal }) =>
      list<Dataset>("/datasets/", { page_size: 200, ...(projectId ? { project: projectId } : {}) }, { signal }),
  });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { split: "dev", is_production: false } });
  const create = useMutation({
    mutationFn: (d: Form) => post<Dataset>("/datasets/", { ...d, project: projectId }),
    onSuccess: async (d) => {
      const createdProjectId = d.project || projectId;
      if (!createdProjectId) return;

      qc.setQueryData<Page<Dataset>>(["datasets", createdProjectId], (current) => addCreatedDataset(current, d));
      await qc.invalidateQueries({ queryKey: ["datasets", createdProjectId] });
      selectDatasetForProject(createdProjectId, d.id);

      toast.success(`Dataset "${d.name}" created and selected`);
      reset();
    },
    onError: (e: ApiError) => toast.error(e.message),
  });
  const activeDataset = datasets.data?.results.find((dataset) => dataset.id === datasetId);
  const journey = useJourneyDashboard(projectId, datasetId);
  const datasetCount = datasets.data?.results.length ?? 0;
  const isFirstDataset = datasets.isSuccess && datasetCount === 0;
  const documentCount = docs.data?.count ?? journey.data?.guidance.documents.total;
  const uploadDocuments = (
    <UploadDropzone
      datasetId={datasetId ?? ""}
      onDone={(summary) => {
        setLastUpload(summary);
        void qc.invalidateQueries({ queryKey: ["documents"] });
        void qc.invalidateQueries({ queryKey: ["datasets"] });
        void qc.invalidateQueries({ queryKey: ["dashboard"] });
      }}
    />
  );
  if (!projectId)
    return (
      <div>
        <PageHeader title="Datasets & documents" />
        <EmptyState
          text="Choose an active project in the sidebar first."
          action={
            <Link to="/projects" className="btn btn-primary btn-sm">
              Go to projects
            </Link>
          }
        />
      </div>
    );
  return (
    <div>
      <PageHeader title={datasetId ? (activeDataset?.name ?? "Selected dataset") : "Datasets & documents"}>
        {datasetId ? (
          <>
            <span>Dataset</span>
            {activeDataset && (
              <>
                <span aria-hidden="true">·</span>
                <span>{SPLIT_PURPOSE[activeDataset.split]}</span>
              </>
            )}
            {documentCount != null && (
              <>
                <span aria-hidden="true">·</span>
                <span>
                  {documentCount.toLocaleString()} document{documentCount === 1 ? "" : "s"}
                </span>
              </>
            )}
            {activeDataset?.is_production && <span className="badge badge-outline badge-sm">Production data</span>}
          </>
        ) : (
          "Choose an existing dataset or create one for a distinct collection of documents."
        )}
      </PageHeader>
      {canOperate &&
        datasetId &&
        (documentCount === 0 ? (
          <Card title="Upload documents" className="mb-6">
            {uploadDocuments}
          </Card>
        ) : (
          <details className="collapse collapse-arrow mb-6 border border-base-300 bg-base-100">
            <summary className="collapse-title min-h-12 pr-12 font-semibold">Add documents</summary>
            <div className="collapse-content">{uploadDocuments}</div>
          </details>
        ))}
      {datasetId && journey.data && journey.data.guidance.documents.total > 0 && (
        <JourneyCue
          action={nextDatasetAction({
            dashboard: journey.data,
            projectId,
            datasetId,
            roles: user?.roles ?? [],
          })}
          className="mb-6"
        />
      )}
      {lastUpload && (
        <output className="sr-only">
          Upload complete: {lastUpload.accepted} accepted
          {lastUpload.reused ? ` (${lastUpload.reused} already present)` : ""}, {lastUpload.rejected} rejected,{" "}
          {lastUpload.failed} failed.
        </output>
      )}
      {!datasetId && (
        <EmptyState
          text={
            datasetCount > 0
              ? "Choose an existing dataset in the sidebar to view or upload its documents."
              : canOperate
                ? "This project has no datasets yet. Create the first dataset below, then upload its documents."
                : "This project has no datasets yet. Ask an operator to create one."
          }
        />
      )}
      {datasetId && (
        <>
          <div className="mb-4 flex flex-wrap items-end gap-3" aria-labelledby="dataset-documents-heading">
            <div className="mr-auto min-w-0 self-start">
              <h2 id="dataset-documents-heading" className="text-lg font-semibold">
                Documents
              </h2>
              <p className="text-sm text-secondary">Files currently stored in this dataset.</p>
            </div>
            <TableSearch
              id="documents-search"
              className="w-full sm:max-w-sm"
              value={search}
              onChange={setSearch}
              placeholder="File name, hash, or document text"
            />
            <label className="flex items-center gap-2 text-sm">
              Status
              <select
                className="select border-(--border-interactive) select-sm"
                value={state.filters.status || ""}
                onChange={(e) => update({ filters: { status: e.target.value } })}
              >
                <option value="">All</option>
                {["validated", "processed", "processing", "failed", "rejected"].map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm">
              Format
              <select
                className="select border-(--border-interactive) select-sm"
                value={state.filters.file_format || ""}
                onChange={(e) => update({ filters: { file_format: e.target.value } })}
              >
                <option value="">All</option>
                {["pdf", "xlsx", "xls", "docx", "png", "jpeg", "tiff", "txt"].map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <DataTable<Document>
            caption="Documents in the active dataset"
            data={docs.data}
            isLoading={docs.isLoading}
            isFetching={docs.isFetching}
            error={docs.error as Error}
            onRetry={() => docs.refetch()}
            state={state}
            update={update}
            getRowId={(r) => r.id}
            columns={[
              {
                id: "original_filename",
                header: "File",
                accessorKey: "original_filename",
                cell: (c) => (
                  <FileNameLink name={c.getValue<string>()} to={`/documents/${c.row.original.id}?from=datasets`} />
                ),
              },
              { id: "file_format", header: "Format", accessorKey: "file_format" },
              {
                id: "page_count",
                meta: { numeric: true },
                header: "Pages / sheets",
                enableSorting: true,
                accessorFn: (r) => r.sheet_count || r.page_count,
                cell: (c) => <span className="tabular-nums">{c.getValue<number>()}</span>,
              },
              {
                id: "size_bytes",
                meta: { numeric: true },
                header: "Size",
                accessorKey: "size_bytes",
                cell: (c) => <span className="tabular-nums">{fmtBytes(c.getValue<number>())}</span>,
              },
              {
                id: "status",
                header: "Status",
                accessorKey: "status",
                cell: (c) => {
                  const issue = c.row.original.validation_errors?.[0];
                  return (
                    <div className="flex max-w-52 flex-col items-start gap-1.5 py-1">
                      <StatusChip status={c.getValue<string>()} />
                      {issue && (
                        <p className="text-caption leading-snug text-secondary">
                          <span className="font-medium text-base-content">Reason:</span> {issue.message}
                        </p>
                      )}
                    </div>
                  );
                },
              },
              { id: "created", header: "Uploaded", accessorKey: "created", cell: (c) => fmtDate(c.getValue<string>()) },
            ]}
            emptyText={
              <span>
                No documents are stored in this dataset yet. Use the upload area above to add the first files.
              </span>
            }
          />
        </>
      )}
      {canOperate && (
        <details
          className="collapse collapse-arrow mt-8 border border-base-300 bg-base-100"
          open={isFirstDataset || undefined}
        >
          <summary className="collapse-title min-h-12 pr-12">
            <span className="block font-semibold">
              {isFirstDataset ? "Create your first dataset" : "Create a separate dataset"}
            </span>
            <span className="mt-1 block text-sm font-normal text-secondary">
              Use a separate dataset when documents need a different data split, provenance, or production boundary.
            </span>
          </summary>
          <div className="collapse-content">
            <p className="reading-copy mb-4 text-sm text-secondary">
              A dataset is a stable collection within the current project. Add repeat uploads to the selected dataset;
              you do not need a new dataset for each upload or processing run. After creation, this page switches to the
              new dataset automatically.
            </p>
            <form
              className="grid gap-x-4 gap-y-5 md:grid-cols-2"
              onSubmit={handleSubmit((d) => create.mutate(d))}
              noValidate
            >
              <Field id="datasets-name" label="Dataset name" required>
                <input
                  id="datasets-name"
                  className={`input w-full ${errors.name ? "input-error" : "border-(--border-interactive)"}`}
                  {...register("name")}
                  required
                  aria-invalid={!!errors.name}
                  aria-describedby={errors.name ? "dataset-name-err" : "dataset-name-help"}
                />
                {errors.name ? (
                  <span id="dataset-name-err" className="text-error text-sm">
                    {errors.name.message}
                  </span>
                ) : (
                  <span id="dataset-name-help" className="text-caption text-secondary">
                    Use a recognizable collection name, such as “Mortgage forms — development.”
                  </span>
                )}
              </Field>
              <Field id="datasets-split" label="Data split">
                <select
                  id="datasets-split"
                  className="select w-full border-(--border-interactive)"
                  {...register("split")}
                  aria-describedby="dataset-split-help"
                >
                  {SPLIT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <span id="dataset-split-help" className="text-caption text-secondary">
                  Keep test data separate so it does not influence prompt or configuration changes.
                </span>
              </Field>
              <label className="min-h-11 cursor-pointer items-start gap-3 md:col-span-2">
                <span className="flex items-center gap-3">
                  <input type="checkbox" className="checkbox" {...register("is_production")} />
                  <span className="font-medium">This dataset contains production data</span>
                </span>
                <span className="ml-9 mt-1 block text-caption text-secondary">
                  Unapproved workflow experiments will be flagged for this dataset.
                </span>
              </label>
              <div className="md:col-span-2">
                <AsyncButton
                  type="submit"
                  className="btn btn-sm"
                  pending={create.isPending}
                  pendingLabel="Creating and selecting…"
                >
                  Create and select dataset
                </AsyncButton>
              </div>
            </form>
          </div>
        </details>
      )}
    </div>
  );
}
