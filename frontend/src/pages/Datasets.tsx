import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { ApiError, list, post, tableParams } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { Dataset, Document } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { UploadDropzone } from "@/components/UploadDropzone";
import { AsyncButton, Card, EmptyState, PageHeader, StatusChip, TableSearch, fmtBytes, fmtDate } from "@/components/ui";
import { useDebouncedSearch, useTableState } from "@/hooks/useTableState";
import { usePrefs } from "@/store/prefs";

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

export function Datasets() {
  const { user } = useSession();
  const canOperate = !!user?.roles.includes("docai_operators");
  const { projectId, datasetId } = usePrefs();
  const qc = useQueryClient();
  const { state, update } = useTableState(["status", "file_format"]);
  const [search, setSearch] = useDebouncedSearch(state.q, (value) => update({ q: value }));
  const docs = useQuery({
    queryKey: ["documents", datasetId, state],
    enabled: !!datasetId,
    queryFn: () => list<Document>("/documents/", { ...tableParams(state), dataset: datasetId }),
  });
  const datasets = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => list<Dataset>("/datasets/", { page_size: 200, ...(projectId ? { project: projectId } : {}) }),
  });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { split: "dev", is_production: false } });
  const create = useMutation({
    mutationFn: (d: Form) => post<Dataset>("/datasets/", { ...d, project: projectId }),
    onSuccess: (d) => {
      toast.success(`Dataset "${d.name}" created`);
      reset();
      qc.invalidateQueries({ queryKey: ["datasets"] });
      usePrefs.getState().setContext(projectId, d.id);
    },
    onError: (e: ApiError) => toast.error(e.message),
  });
  const activeDataset = datasets.data?.results.find((dataset) => dataset.id === datasetId);
  const activeSplitLabel = SPLIT_OPTIONS.find((option) => option.value === activeDataset?.split)?.label.split(" — ")[0];
  const datasetCount = datasets.data?.results.length ?? 0;
  const isFirstDataset = datasets.isSuccess && datasetCount === 0;
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
      <PageHeader title="Datasets & documents">
        Work in one dataset at a time. The project and dataset selected in the sidebar control where uploads go and
        which documents appear below.
      </PageHeader>
      {datasetId && (
        <section
          aria-labelledby="current-dataset-heading"
          className="mb-4 flex flex-wrap items-start justify-between gap-3 rounded-box border border-base-300 bg-base-200 p-4"
        >
          <div className="min-w-0">
            <p className="text-caption font-semibold uppercase tracking-wide text-secondary">Current dataset</p>
            <h2 id="current-dataset-heading" className="mt-1 text-lg font-semibold [overflow-wrap:anywhere]">
              {activeDataset?.name ?? "Selected dataset"}
            </h2>
            <p className="reading-copy mt-1 text-sm text-secondary">
              Uploads and the document list on this page belong only to this dataset. Change the dataset in the sidebar
              to work with another collection.
            </p>
          </div>
          {activeDataset && (
            <div className="flex flex-wrap gap-2" aria-label="Current dataset attributes">
              <span className="badge badge-outline">
                {activeDataset.split === "unsplit"
                  ? "Unassigned split"
                  : `${activeSplitLabel ?? activeDataset.split} split`}
              </span>
              {activeDataset.is_production && <span className="badge badge-outline">Production data</span>}
            </div>
          )}
        </section>
      )}
      {canOperate && datasetId && (
        <Card title={`Upload documents to ${activeDataset?.name ?? "the selected dataset"}`} className="mb-6">
          <UploadDropzone
            datasetId={datasetId}
            onDone={() => {
              qc.invalidateQueries({ queryKey: ["documents"] });
              qc.invalidateQueries({ queryKey: ["datasets"] });
            }}
          />
        </Card>
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
          <div className="mb-3 flex flex-wrap items-end gap-3" aria-labelledby="dataset-documents-heading">
            <div className="mr-auto min-w-0 self-start">
              <h2 id="dataset-documents-heading" className="text-lg font-semibold">
                Documents
              </h2>
              <p className="text-sm text-secondary">
                Files currently stored in {activeDataset?.name ?? "the selected dataset"}.
              </p>
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
                  <Link className="link link-primary" to={`/review/${c.row.original.id}`}>
                    {c.getValue<string>()}
                  </Link>
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
                cell: (c) => (
                  <>
                    <StatusChip status={c.getValue<string>()} />
                    {c.row.original.validation_errors?.[0] && (
                      <span className="ml-2 text-caption">{c.row.original.validation_errors[0].message}</span>
                    )}
                  </>
                ),
              },
              { id: "created", header: "Uploaded", accessorKey: "created", cell: (c) => fmtDate(c.getValue<string>()) },
            ]}
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
            <form className="grid gap-4 md:grid-cols-2" onSubmit={handleSubmit((d) => create.mutate(d))} noValidate>
              <div className="fieldset min-w-0 gap-2 p-0 text-sm">
                <label className="label whitespace-normal font-medium text-base-content" htmlFor="datasets-name">
                  Dataset name <span aria-hidden>*</span>
                </label>
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
              </div>
              <div className="fieldset min-w-0 gap-2 p-0 text-sm">
                <label className="label whitespace-normal font-medium text-base-content" htmlFor="datasets-split">
                  Data split
                </label>
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
              </div>
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
