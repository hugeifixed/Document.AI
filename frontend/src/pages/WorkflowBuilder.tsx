/** Workflow builder: structured fields (RHF + Zod) for the parts every workflow shares,
 *  a JSON editor for the type-specific body, server-side validation on demand
 *  (POST /workflows/validate/) with the content hash shown before saving. */
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { apiFieldError, errorMessage, get, post } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { Workflow, WorkflowCapabilities } from "@/api/types";
import { ErrorNotice } from "@/components/ErrorNotice";
import { AsyncButton, Breadcrumbs, Card, EmptyState, Field, PageHeader } from "@/components/ui";
import { useWorkingContext } from "@/workspace/context";
import { useWorkspaceDraft } from "@/workspace/navigation";

const schema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters").max(120),
  workflow_type: z.string().min(1),
  deployment: z.string().min(1, "Deployment is required"),
  temperature: z.number().min(0).max(2),
  strategy: z.enum(["whole_document", "page", "sheet", "context_length", "semantic"]),
  chunk_chars: z.number().int().min(2000).max(200000),
  overlap_chars: z.number().int().min(0).max(20000),
  fallback: z.enum(["context_length", "page", "semantic", "none"]),
  tables_as_markdown: z.boolean(),
  include_source_ids: z.boolean(),
  link_row_bands: z.boolean(),
  input_quality_mode: z.enum(["off", "adaptive"]),
  skip_blank_pages: z.boolean(),
  ocr_high_resolution: z.boolean(),
});
type Form = z.infer<typeof schema>;
type WorkflowRequest = { workflow_type: string; config: Record<string, unknown> };
type ComposedWorkflow = { ok: true; request: WorkflowRequest } | { ok: false; message: string };

const EXAMPLES: Record<string, unknown> = {
  unbundle_classify_extract: {
    categories: [
      {
        key: "w2",
        name: "Form W-2",
        description: "IRS wage statement",
        distinguishing_evidence: "'Form W-2', box 1 wages",
        extraction_schema: "w2",
      },
    ],
    schemas: [
      {
        name: "w2",
        fields: [
          { name: "employee_ssn", type: "identifier", required: true, description: "Employee SSN (box a)" },
          { name: "wages_box1", type: "currency", description: "Box 1 wages" },
        ],
      },
    ],
    other_behavior: "needs_review",
    routing: [
      { when: { validation_failed: true }, outcome: "human_review" },
      { when: { min_score: 0.85 }, outcome: "auto_accept" },
    ],
  },
  classify_structured: {
    rules: [
      {
        category: "w2",
        required: [{ pattern: "Form W-2", kind: "form_id", weight: 2 }],
        optional: [{ pattern: "Wage and Tax Statement", kind: "phrase" }],
        exclusions: [{ pattern: "1099", kind: "phrase" }],
        threshold: 2,
      },
    ],
    use_llm_fallback: true,
    categories: [{ key: "w2", name: "Form W-2" }],
  },
  classify_unstructured: {
    categories: [
      { key: "w2", name: "Form W-2", description: "IRS wage statement" },
      { key: "paystub", name: "Pay stub", description: "Earnings statement" },
    ],
  },
  extract_structured: { mode: "default" },
  extract_unstructured: {
    schema: {
      name: "note",
      fields: [
        { name: "borrower_name", type: "string", required: true },
        { name: "principal_amount", type: "currency" },
      ],
    },
    document_type: "promissory_note",
    reconciliation: { policy: "highest_score" },
  },
  extract_template: { template_name: "w2-template", template_version: 1 },
};

export function composeWorkflow(form: Form, body: string): ComposedWorkflow {
  let extra: unknown;
  try {
    extra = JSON.parse(body);
  } catch (error) {
    return { ok: false, message: `Invalid JSON: ${errorMessage(error)}` };
  }
  if (!extra || typeof extra !== "object" || Array.isArray(extra))
    return { ok: false, message: "Type-specific configuration must be a JSON object." };
  const base =
    form.workflow_type === "evaluate"
      ? {}
      : {
          model: { adapter: "azure_openai", deployment: form.deployment, temperature: form.temperature },
          chunking: {
            strategy: form.strategy,
            chunk_chars: form.chunk_chars,
            overlap_chars: form.overlap_chars,
            fallback: form.fallback === "none" ? null : form.fallback,
          },
          input_quality: {
            mode: form.input_quality_mode,
            skip_blank_pages: form.input_quality_mode === "adaptive" && form.skip_blank_pages,
          },
          di_analysis: { ocr_high_resolution: form.ocr_high_resolution },
          layout: {
            tables_as_markdown: form.tables_as_markdown,
            include_source_ids: form.include_source_ids,
            link_row_bands: form.link_row_bands,
          },
        };
  // Structured controls own shared settings: JSON cannot silently override the policy shown above.
  if ("input_quality" in extra || "di_analysis" in extra)
    return {
      ok: false,
      message: "Use the scan enhancement and Document Intelligence controls for processing options.",
    };
  return { ok: true, request: { workflow_type: form.workflow_type, config: { ...base, ...extra } } };
}

function workflowFingerprint(form: Form, body: string) {
  return JSON.stringify([
    form.workflow_type,
    form.deployment,
    form.temperature,
    form.strategy,
    form.chunk_chars,
    form.overlap_chars,
    form.fallback,
    form.tables_as_markdown,
    form.include_source_ids,
    form.link_row_bands,
    form.input_quality_mode,
    form.skip_blank_pages,
    form.ocr_high_resolution,
    body,
  ]);
}

export function WorkflowBuilder() {
  const { user } = useSession();
  const canOperate = !!user?.roles.includes("docai_operators");
  const projectId = useWorkingContext((state) => state.projectId);
  const nav = useNavigate();
  const types = useQuery({
    queryKey: ["workflow-types"],
    queryFn: ({ signal }) =>
      get<Record<string, { label: string; schema: unknown }>>("/workflows/types/", undefined, { signal }),
  });
  const capabilities = useQuery({
    queryKey: ["workflow-capabilities"],
    queryFn: ({ signal }) => get<WorkflowCapabilities>("/workflows/capabilities/", undefined, { signal }),
    enabled: canOperate,
  });
  const {
    register,
    handleSubmit,
    watch,
    reset,
    formState: { errors, isDirty },
  } = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: "",
      workflow_type: "unbundle_classify_extract",
      deployment: "gpt-4o",
      temperature: 0,
      strategy: "whole_document",
      chunk_chars: 24000,
      overlap_chars: 1500,
      fallback: "context_length",
      tables_as_markdown: true,
      include_source_ids: true,
      link_row_bands: true,
      input_quality_mode: "off",
      skip_blank_pages: false,
      ocr_high_resolution: false,
    },
  });
  const formValues = watch();
  const wt = formValues.workflow_type;
  const [body, setBody] = useState(JSON.stringify(EXAMPLES.unbundle_classify_extract, null, 2));
  const [savedBody, setSavedBody] = useState(body);
  const [jsonErr, setJsonErr] = useState<string | null>(null);
  const [validated, setValidated] = useState<{ content_hash: string; fingerprint: string } | null>(null);
  useEffect(() => {
    setBody(JSON.stringify(EXAMPLES[wt] ?? {}, null, 2));
    setJsonErr(null);
  }, [wt]);
  const currentFingerprint = workflowFingerprint(formValues, body);
  const validationIsCurrent = validated?.fingerprint === currentFingerprint;
  const prepare = (form: Form) => {
    if (
      form.workflow_type !== "evaluate" &&
      form.input_quality_mode === "adaptive" &&
      !capabilities.data?.image_normalization?.available
    ) {
      setJsonErr(
        "Scan enhancement is unavailable in this environment. Choose Use original or retry the capability check.",
      );
      return null;
    }
    const composed = composeWorkflow(form, body);
    if (!composed.ok) {
      setJsonErr(composed.message);
      return null;
    }
    setJsonErr(null);
    return { ...composed, fingerprint: workflowFingerprint(form, body) };
  };
  const validate = useMutation({
    mutationFn: ({ request }: { request: WorkflowRequest; fingerprint: string }) =>
      post<{ valid: boolean; content_hash: string }>("/workflows/validate/", request),
    onSuccess: (result, variables) => {
      setValidated({ content_hash: result.content_hash, fingerprint: variables.fingerprint });
      toast.success("Configuration is valid");
    },
    onError: (error: unknown) => {
      setValidated(null);
      toast.error(apiFieldError(error, "config") ?? errorMessage(error));
    },
  });
  const create = useMutation({
    mutationFn: ({ form, request }: { form: Form; request: WorkflowRequest }) =>
      post<Workflow>("/workflows/", { project: projectId, name: form.name, ...request }),
    onSuccess: (workflow, { form }) => {
      reset(form);
      setSavedBody(body);
      toast.success(`Created ${workflow.name} v${workflow.version}`);
      nav(`/configurations?created=${workflow.id}`);
    },
    onError: (error: unknown) => toast.error(apiFieldError(error, "config") ?? errorMessage(error)),
  });
  useWorkspaceDraft(canOperate && (isDirty || body !== savedBody), create.isPending);
  const validateForm = handleSubmit((form) => {
    const composed = prepare(form);
    if (composed) validate.mutate(composed);
  });
  const createForm = handleSubmit((form) => {
    const composed = prepare(form);
    if (!composed) return;
    if (validated?.fingerprint !== composed.fingerprint) {
      toast.error("Validate the current configuration before creating a version.");
      return;
    }
    create.mutate({ form, request: composed.request });
  });
  if (!canOperate)
    return (
      <div>
        <Breadcrumbs
          items={[{ label: "Workflow versions", to: "/configurations" }, { label: "New workflow version" }]}
        />
        <PageHeader title="New workflow version" />
        <EmptyState
          text="Creating workflow versions requires the operator role."
          action={
            <Link className="btn btn-outline btn-sm" to="/configurations">
              View workflow versions
            </Link>
          }
        />
      </div>
    );
  if (!projectId)
    return (
      <div>
        <Breadcrumbs
          items={[{ label: "Workflow versions", to: "/configurations" }, { label: "New workflow version" }]}
        />
        <PageHeader title="New workflow version" />
        <p>Select an active project in the sidebar first.</p>
      </div>
    );
  const err = (k: keyof Form) =>
    errors[k] && (
      <span id={`workflow-${k}-error`} className="text-error text-sm">
        {String(errors[k]?.message)}
      </span>
    );
  return (
    <div>
      <Breadcrumbs items={[{ label: "Workflow versions", to: "/configurations" }, { label: "New workflow version" }]} />
      <PageHeader title="New workflow version">
        Saving creates a new immutable version. Validate first to see the content hash the run will record.
      </PageHeader>
      {types.isError && (
        <div className="mb-4">
          <ErrorNotice
            message={errorMessage(types.error, "Workflow types could not be loaded.")}
            onRetry={() => types.refetch()}
          />
        </div>
      )}
      <form onSubmit={createForm} noValidate>
        <fieldset disabled={create.isPending} className="grid min-w-0 gap-4 lg:grid-cols-2">
          <Card title="Identity">
            <div className="grid gap-5">
              <Field id="workflowbuilder-name" label="Name" required>
                <input
                  id="workflowbuilder-name"
                  className={`input w-full ${errors.name ? "input-error" : "border-(--border-interactive)"}`}
                  aria-invalid={!!errors.name}
                  aria-describedby={errors.name ? "workflow-name-error" : undefined}
                  {...register("name")}
                  required
                />
                {err("name")}
              </Field>
              <Field id="workflowbuilder-workflow-type" label="Workflow type">
                <select
                  id="workflowbuilder-workflow-type"
                  className="select border-(--border-interactive) w-full"
                  disabled={!types.data}
                  {...register("workflow_type")}
                  value={wt}
                >
                  {types.data ? (
                    Object.entries(types.data)
                      .filter(([k]) => k !== "evaluate")
                      .map(([k, v]) => (
                        <option key={k} value={k}>
                          {v.label}
                        </option>
                      ))
                  ) : (
                    <option>{types.isError ? "Unavailable" : "Loading…"}</option>
                  )}
                </select>
              </Field>
            </div>
          </Card>
          <Card title="Model">
            <div className="grid gap-5">
              <Field id="workflowbuilder-deployment" label="Azure OpenAI deployment">
                <input
                  id="workflowbuilder-deployment"
                  className="input border-(--border-interactive) w-full"
                  aria-invalid={!!errors.deployment}
                  aria-describedby={errors.deployment ? "dep-help workflow-deployment-error" : "dep-help"}
                  {...register("deployment")}
                />
                <span id="dep-help" className="text-caption text-secondary">
                  Identity-based auth; no keys. Swapping models never changes workflow logic.
                </span>
                {err("deployment")}
              </Field>
              <Field id="workflowbuilder-temperature" label="Temperature">
                <input
                  id="workflowbuilder-temperature"
                  className="input border-(--border-interactive) w-32"
                  type="number"
                  step="0.1"
                  min={0}
                  max={2}
                  aria-invalid={!!errors.temperature}
                  aria-describedby={errors.temperature ? "workflow-temperature-error" : undefined}
                  {...register("temperature", { valueAsNumber: true })}
                />
                {err("temperature")}
              </Field>
            </div>
          </Card>
          <Card title="Chunking">
            <div className="grid gap-x-4 gap-y-5 md:grid-cols-2">
              <Field id="workflowbuilder-strategy" label="Strategy">
                <select
                  id="workflowbuilder-strategy"
                  className="select border-(--border-interactive) w-full"
                  {...register("strategy")}
                >
                  {["whole_document", "page", "sheet", "context_length", "semantic"].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </Field>
              <Field id="workflowbuilder-fallback" label="Fallback (explicit, recorded)">
                <select
                  id="workflowbuilder-fallback"
                  className="select border-(--border-interactive) w-full"
                  {...register("fallback")}
                >
                  {["context_length", "page", "semantic", "none"].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </Field>
              <Field id="workflowbuilder-chunk-chars" label="Chunk size (chars)">
                <input
                  id="workflowbuilder-chunk-chars"
                  className="input border-(--border-interactive) w-full"
                  type="number"
                  aria-invalid={!!errors.chunk_chars}
                  aria-describedby={errors.chunk_chars ? "workflow-chunk_chars-error" : undefined}
                  {...register("chunk_chars", { valueAsNumber: true })}
                />
                {err("chunk_chars")}
              </Field>
              <Field id="workflowbuilder-overlap-chars" label="Overlap (chars)">
                <input
                  id="workflowbuilder-overlap-chars"
                  className="input border-(--border-interactive) w-full"
                  type="number"
                  aria-invalid={!!errors.overlap_chars}
                  aria-describedby={errors.overlap_chars ? "workflow-overlap_chars-error" : undefined}
                  {...register("overlap_chars", { valueAsNumber: true })}
                />
                {err("overlap_chars")}
              </Field>
            </div>
          </Card>
          <Card title="Layout preservation (non-LLM)">
            <div className="grid gap-3">
              <label className="flex items-center gap-2">
                <input type="checkbox" className="checkbox" {...register("tables_as_markdown")} /> Render tables as
                markdown with cell ids
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" className="checkbox" {...register("include_source_ids")} /> Include stable source
                ids (required for grounding)
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" className="checkbox" {...register("link_row_bands")} /> Link same-row form fields
                (label ↔ value)
              </label>
            </div>
          </Card>
          {wt !== "evaluate" && (
            <>
              <Card title="Scan enhancement">
                <div className="grid gap-5">
                  <p className="text-sm text-secondary">
                    The original upload is always preserved. Enhancement runs before document analysis.
                  </p>
                  <Field id="workflowbuilder-scan-mode" label="Processing source">
                    <select
                      id="workflowbuilder-scan-mode"
                      className="select border-(--border-interactive) w-full"
                      {...register("input_quality_mode")}
                      aria-describedby="scan-availability"
                    >
                      <option value="off">Use original</option>
                      <option value="adaptive" disabled={!capabilities.data?.image_normalization?.available}>
                        Improve scanned pages
                      </option>
                    </select>
                  </Field>
                  <p id="scan-availability" className="text-caption text-secondary">
                    {capabilities.isError
                      ? "Availability could not be checked. Original processing is available."
                      : capabilities.isPending
                        ? "Checking scan enhancement availability…"
                        : capabilities.data?.image_normalization?.available
                          ? "Experimental: adjusts eligible scanned pages; digital content is preserved."
                          : capabilities.data?.image_normalization?.reason ||
                            "Scan enhancement is disabled in this environment."}
                    {capabilities.isError && (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => void capabilities.refetch()}
                      >
                        Retry availability
                      </button>
                    )}
                  </p>
                  {formValues.input_quality_mode === "adaptive" && (
                    <label className="flex min-h-10 items-start gap-2">
                      <input
                        type="checkbox"
                        className="checkbox shrink-0"
                        {...register("skip_blank_pages")}
                        aria-describedby="skip-blanks-help"
                      />
                      <span>
                        Skip confidently blank pages during analysis
                        <span id="skip-blanks-help" className="block text-caption text-secondary">
                          Optional. Pages stay in the file and retain their numbering. Leave off for faint or sparse
                          forms.
                        </span>
                      </span>
                    </label>
                  )}
                </div>
              </Card>
              <Card title="Document Intelligence">
                <label className="flex min-h-10 items-start gap-2">
                  <input
                    type="checkbox"
                    className="checkbox shrink-0"
                    {...register("ocr_high_resolution")}
                    disabled={!capabilities.data?.di_analysis?.ocr_high_resolution}
                    aria-describedby="high-resolution-help"
                  />
                  <span>
                    High-resolution OCR
                    <span id="high-resolution-help" className="block text-caption text-secondary">
                      Azure add-on for small text, independent of scan enhancement. Additional provider charges apply.
                      {!capabilities.data?.di_analysis?.ocr_high_resolution &&
                        " Unavailable with the current analysis adapter."}
                    </span>
                  </span>
                </label>
              </Card>
            </>
          )}
          <Card title={`Type-specific configuration (${wt})`} className="lg:col-span-2">
            <p className="mb-3 text-sm text-secondary">
              Categories, schemas, rules, routing. The server validates against the workflow's Pydantic schema; errors
              are returned verbatim.
            </p>
            <textarea
              className={`textarea font-mono h-72 w-full text-sm leading-normal ${jsonErr ? "textarea-error" : "border-(--border-interactive)"}`}
              value={body}
              onChange={(e) => {
                setBody(e.target.value);
                setJsonErr(null);
              }}
              aria-label="Type-specific configuration JSON"
              aria-invalid={!!jsonErr}
              aria-describedby={jsonErr ? "workflow-json-error" : undefined}
              spellCheck={false}
            />
            {jsonErr && (
              <p id="workflow-json-error" className="text-error text-sm">
                {jsonErr}
              </p>
            )}
            <details className="mt-3 text-sm">
              <summary>JSON schema for this type</summary>
              <pre className="font-mono text-sm leading-normal max-h-64 overflow-auto rounded bg-base-200 p-2">
                {JSON.stringify(types.data?.[wt]?.schema ?? {}, null, 2)}
              </pre>
            </details>
          </Card>
          <div className="flex flex-wrap items-center gap-3 lg:col-span-2">
            <AsyncButton
              className="btn btn-outline"
              onClick={validateForm}
              pending={validate.isPending}
              pendingLabel="Validating…"
              disabled={create.isPending || !types.data}
            >
              Validate
            </AsyncButton>
            {validationIsCurrent && (
              <span className="text-sm">
                Valid · hash <span className="font-mono">{validated.content_hash.slice(7, 23)}…</span>
              </span>
            )}
            <AsyncButton
              type="submit"
              className="btn btn-primary"
              pending={create.isPending}
              pendingLabel="Creating…"
              disabled={validate.isPending || !validationIsCurrent}
            >
              Create version
            </AsyncButton>
          </div>
        </fieldset>
      </form>
    </div>
  );
}
