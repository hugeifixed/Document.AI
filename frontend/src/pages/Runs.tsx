import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { apiFieldError, errorMessage, list } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { Dataset, Run, Workflow } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import {
  AsyncButton,
  Card,
  EmptyState,
  Field,
  fmtDate,
  PageHeader,
  SelectControl,
  StatusChip,
  TableSearch,
} from "@/components/ui";
import { useDebouncedSearch, useTableState } from "@/hooks/useTableState";
import { useJourneyDashboard } from "@/journey/guidance";
import { RUN_STATUSES, useCreateRun, useRunCollection } from "@/runs/lifecycle";
import { useWorkingContext } from "@/workspace/context";

const runSchema = z.object({
  workflow: z.string().min(1, "Choose a workflow."),
  dataset: z.string().min(1, "Choose a dataset."),
  name: z.string(),
  sample: z
    .string()
    .refine(
      (value) => value === "" || (/^\d+$/.test(value) && Number(value) >= 1),
      "Enter a whole number of at least 1.",
    ),
});
type RunForm = z.infer<typeof runSchema>;

export function Runs() {
  const { user } = useSession();
  const canOperate = !!user?.roles.includes("docai_operators");
  const { projectId, datasetId, selectDataset } = useWorkingContext();
  const nav = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedDataset = searchParams.get("dataset");
  const requestedWorkflow = searchParams.get("workflow");
  const { state, update } = useTableState(["status"]);
  const [search, setSearch] = useDebouncedSearch(state.q, (value) => update({ q: value }));
  const q = useRunCollection({ purpose: "manage", projectId, datasetId, table: state });
  const wfs = useQuery({
    queryKey: ["workflows", projectId, "all"],
    enabled: !!projectId,
    queryFn: ({ signal }) =>
      list<Workflow>("/workflows/", { page_size: 200, project: projectId, status__in: "draft,approved" }, { signal }),
  });
  const dss = useQuery({
    queryKey: ["datasets", projectId],
    enabled: !!projectId,
    queryFn: ({ signal }) => list<Dataset>("/datasets/", { page_size: 200, project: projectId }, { signal }),
  });
  const {
    register,
    handleSubmit,
    setError,
    setValue,
    watch,
    formState: { errors },
  } = useForm<RunForm>({
    resolver: zodResolver(runSchema),
    defaultValues: { workflow: "", dataset: datasetId ?? "", name: "", sample: "" },
  });
  const selectedDatasetId = watch("dataset");
  const journey = useJourneyDashboard(projectId, selectedDatasetId || datasetId);
  useEffect(() => setValue("workflow", ""), [projectId, setValue]);
  useEffect(() => {
    const preferred = requestedDataset || datasetId;
    const available = preferred && dss.data?.results.some((dataset) => dataset.id === preferred);
    const value = available ? preferred : "";
    setValue("dataset", value, { shouldValidate: false });
    if (value && value !== datasetId) selectDataset(value);
  }, [datasetId, dss.data, requestedDataset, selectDataset, setValue]);
  useEffect(() => {
    if (!wfs.data) return;
    const requested = requestedWorkflow && wfs.data.results.some((workflow) => workflow.id === requestedWorkflow);
    const onlyWorkflow = wfs.data.results.length === 1 ? wfs.data.results[0]?.id : undefined;
    setValue("workflow", requested ? requestedWorkflow : (onlyWorkflow ?? ""), { shouldValidate: false });
  }, [requestedWorkflow, setValue, wfs.data]);
  const create = useCreateRun();
  const submit = (values: RunForm) =>
    create.mutate(
      {
        project: projectId,
        workflow: values.workflow,
        dataset: values.dataset,
        name: values.name,
        sample_size: values.sample ? Number(values.sample) : undefined,
        execute: true,
      },
      {
        onSuccess: (run) => {
          toast.success(`Run ${run.status}`);
          nav(`/runs/${run.id}`);
        },
        onError: (error: unknown) => {
          for (const [serverName, formName] of [
            ["workflow", "workflow"],
            ["dataset", "dataset"],
            ["name", "name"],
            ["sample_size", "sample"],
          ] as const) {
            const message = apiFieldError(error, serverName);
            if (message) setError(formName, { type: "server", message });
          }
          toast.error(errorMessage(error));
        },
      },
    );
  return (
    <div>
      <PageHeader title="Runs">
        Every run snapshots its configuration (hash), prompt and schema versions, and adapters.
      </PageHeader>
      {!projectId && (
        <EmptyState
          text="Choose a project before starting a run."
          action={
            <Link className="btn btn-primary btn-sm" to="/projects">
              Choose project
            </Link>
          }
        />
      )}
      {projectId && canOperate && dss.isSuccess && dss.data.results.length === 0 && (
        <EmptyState
          text="This project has no datasets. Create one and upload documents before starting a run."
          action={
            <Link className="btn btn-primary btn-sm" to="/datasets">
              Create dataset
            </Link>
          }
        />
      )}
      {projectId && canOperate && dss.data?.results.length !== 0 && wfs.isSuccess && wfs.data.results.length === 0 && (
        <EmptyState
          text="This project has no runnable workflow versions. Create one before starting a run."
          action={
            <Link className="btn btn-primary btn-sm" to="/workflows/new">
              Create workflow version
            </Link>
          }
        />
      )}
      {projectId &&
        canOperate &&
        journey.data &&
        selectedDatasetId &&
        journey.data.guidance.documents.runnable === 0 && (
          <EmptyState
            text={
              journey.data.guidance.documents.total
                ? "The selected dataset has no documents that can be included in a run. Review its validation issues first."
                : "The selected dataset is empty. Upload documents before starting a run."
            }
            action={
              <Link className="btn btn-primary btn-sm" to="/datasets">
                Open dataset
              </Link>
            }
          />
        )}
      {projectId &&
        canOperate &&
        dss.data?.results.length !== 0 &&
        wfs.data?.results.length !== 0 &&
        (!selectedDatasetId || !journey.data || journey.data.guidance.documents.runnable > 0) && (
          <Card title="Start a run" className="mb-6">
            {selectedDatasetId && journey.data && (
              <p className="reading-copy mb-4 text-sm text-secondary">
                {journey.data.guidance.documents.runnable.toLocaleString()} ready document
                {journey.data.guidance.documents.runnable === 1 ? "" : "s"} will be available. Confirm the workflow and
                use a sample only when you intentionally want a smaller run.
              </p>
            )}
            <form
              className="grid items-start gap-x-4 gap-y-5 sm:grid-cols-2 xl:grid-cols-4"
              onSubmit={handleSubmit(submit)}
            >
              <Field id="runs-workflow" label="Workflow" required>
                <SelectControl
                  id="runs-workflow"
                  className={`border-(--border-interactive) ${errors.workflow ? "select-error" : ""}`}
                  {...register("workflow")}
                  required
                  aria-invalid={!!errors.workflow}
                  aria-describedby={errors.workflow ? "runs-workflow-error" : undefined}
                >
                  <option value="">Select…</option>
                  {wfs.data?.results.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name} v{w.version} ({w.status})
                    </option>
                  ))}
                </SelectControl>
                {errors.workflow && (
                  <p id="runs-workflow-error" className="field-error text-sm text-error">
                    {errors.workflow.message}
                  </p>
                )}
              </Field>
              <Field id="runs-dataset" label="Dataset" required>
                <SelectControl
                  id="runs-dataset"
                  className={`border-(--border-interactive) ${errors.dataset ? "select-error" : ""}`}
                  {...register("dataset")}
                  required
                  aria-invalid={!!errors.dataset}
                  aria-describedby={errors.dataset ? "runs-dataset-error" : undefined}
                >
                  <option value="">Select…</option>
                  {dss.data?.results.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name} ({d.split}, {d.document_count})
                    </option>
                  ))}
                </SelectControl>
                {errors.dataset && (
                  <p id="runs-dataset-error" className="field-error text-sm text-error">
                    {errors.dataset.message}
                  </p>
                )}
              </Field>
              <Field id="runs-name" label="Name">
                <input
                  id="runs-name"
                  className={`input w-full border-(--border-interactive) ${errors.name ? "input-error" : ""}`}
                  {...register("name")}
                  aria-invalid={!!errors.name}
                  aria-describedby={errors.name ? "runs-name-error" : undefined}
                />
                {errors.name && (
                  <p id="runs-name-error" className="field-error text-sm text-error">
                    {errors.name.message}
                  </p>
                )}
              </Field>
              <Field id="runs-sample" label="Sample (docs)">
                <input
                  id="runs-sample"
                  className={`input w-full border-(--border-interactive) ${errors.sample ? "input-error" : ""}`}
                  type="number"
                  min={1}
                  step={1}
                  inputMode="numeric"
                  {...register("sample")}
                  aria-invalid={!!errors.sample}
                  aria-describedby={errors.sample ? "runs-sample-error" : "sample-help"}
                />
                {errors.sample ? (
                  <p id="runs-sample-error" className="field-error text-sm text-error">
                    {errors.sample.message}
                  </p>
                ) : (
                  <span id="sample-help" className="text-caption text-secondary">
                    Blank = whole dataset
                  </span>
                )}
              </Field>
              <div className="col-span-full">
                <AsyncButton
                  type="submit"
                  className="btn btn-primary"
                  pending={create.isPending}
                  pendingLabel="Starting…"
                >
                  Start run
                </AsyncButton>
              </div>
            </form>
          </Card>
        )}
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <TableSearch
          id="runs-search"
          className="w-full sm:max-w-sm"
          value={search}
          onChange={setSearch}
          placeholder="Run, workflow, dataset, or hash"
        />
        <label className="flex items-center gap-2 text-sm">
          Status
          <select
            className="select border-(--border-interactive) select-sm"
            value={state.filters.status || ""}
            onChange={(e) => update({ filters: { status: e.target.value } })}
          >
            <option value="">All</option>
            {RUN_STATUSES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
      </div>
      <DataTable<Run>
        caption="Runs"
        data={q.data}
        isLoading={q.isLoading}
        isFetching={q.isFetching}
        error={q.error as Error}
        onRetry={() => q.refetch()}
        state={state}
        update={update}
        getRowId={(r) => r.id}
        onRowOpen={(r) => nav(`/runs/${r.id}`)}
        columns={[
          { id: "name", header: "Run", accessorFn: (r) => r.name || r.workflow_name },
          {
            id: "workflow__name",
            header: "Workflow",
            accessorFn: (r) => `${r.workflow_name}`,
            enableSorting: false,
            cell: (c) => <span className="whitespace-nowrap text-secondary">{c.getValue<string>()}</span>,
          },
          {
            id: "status",
            header: "Status",
            accessorKey: "status",
            cell: (c) => <StatusChip status={c.getValue<string>()} />,
          },
          {
            id: "total_items",
            meta: { numeric: true },
            header: "Progress",
            accessorFn: (r) => r,
            enableSorting: true,
            cell: (c) => {
              const r = c.getValue<Run>();
              return (
                <span className="tabular-nums">
                  {r.processed_items}/{r.total_items}
                  {r.failed_items ? ` (${r.failed_items} failed)` : ""}
                </span>
              );
            },
          },
          {
            id: "llm_adapter",
            header: "Adapters",
            enableSorting: false,
            accessorFn: (r) => `${r.layout_adapter} / ${r.llm_adapter}`,
            cell: (c) => (
              <span className="whitespace-nowrap font-mono text-caption text-(--color-ink-3)">
                {c.getValue<string>()}
              </span>
            ),
          },
          { id: "created", header: "Created", accessorKey: "created", cell: (c) => fmtDate(c.getValue<string>()) },
        ]}
        emptyText={
          projectId
            ? "No runs match this view. Use the start form above when this dataset is ready."
            : "Choose a project to view its runs."
        }
      />
    </div>
  );
}
