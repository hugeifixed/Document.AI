import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiError, list, post, tableParams } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { Project } from "@/api/types";
import { DataTable } from "@/components/DataTable";
import { AsyncButton, PageHeader, TableSearch, fmtDate } from "@/components/ui";
import { useDebouncedSearch, useTableState } from "@/hooks/useTableState";
import { usePrefs } from "@/store/prefs";

const schema = z.object({ name: z.string().min(2, "Name must be at least 2 characters").max(120), slug: z.string().regex(/^[a-z0-9-]*$/, "Lowercase letters, numbers and hyphens only").max(64).optional().or(z.literal("")), description: z.string().max(2000).optional() });
type Form = z.infer<typeof schema>;

export function slugFromProjectName(name: string) {
  return name
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/[\s-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64)
    .replace(/-+$/g, "");
}

export function Projects() {
  const { user } = useSession();
  const canOperate = !!user?.roles.includes("docai_operators");
  const { state, update } = useTableState([]);
  const [search, setSearch] = useDebouncedSearch(state.q, (value) => update({ q: value }));
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["projects", state], queryFn: () => list<Project>("/projects/", tableParams(state)) });
  const [slugIsCustom, setSlugIsCustom] = useState(false);
  const { register, handleSubmit, reset, setError, setValue, getValues, formState: { errors, isSubmitting } } = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", slug: "", description: "" },
  });
  const nameField = register("name", {
    onChange: (event) => {
      if (!slugIsCustom) {
        setValue("slug", slugFromProjectName(event.target.value), {
          shouldDirty: true,
          shouldValidate: !!errors.slug,
        });
      }
    },
  });
  const slugField = register("slug", {
    onChange: (event) => {
      setSlugIsCustom(event.target.value !== slugFromProjectName(getValues("name")));
    },
  });
  const create = useMutation({
    mutationFn: (d: Form) => post<Project>("/projects/", { ...d, slug: d.slug || undefined }),
    onSuccess: (p) => { setSlugIsCustom(false); toast.success(`Project "${p.name}" created`); reset(); qc.invalidateQueries({ queryKey: ["projects"] }); },
    onError: (e: ApiError) => { for (const [k, v] of Object.entries(e.errors)) setError(k as keyof Form, { message: String(Array.isArray(v) ? v[0] : v) }); toast.error(e.message); },
  });
  return (
    <div>
      <PageHeader title="Projects">A project groups datasets, configurations and runs for one business use case.</PageHeader>
      {canOperate && <form className="mb-6 grid items-start gap-4 rounded-box border border-base-300 bg-base-100 p-4 lg:grid-cols-3" onSubmit={handleSubmit((d) => create.mutate(d))} noValidate>
        <div className="fieldset min-w-0 gap-2 p-0 text-sm"><label className="label whitespace-normal font-medium text-base-content" htmlFor="projects-name">Name <span aria-hidden>*</span></label><input id="projects-name" className={`input w-full ${errors.name ? "input-error" : "border-(--border-interactive)"}`} {...nameField} aria-invalid={!!errors.name} aria-describedby={errors.name ? "name-err" : undefined} maxLength={120} required />{errors.name && <span id="name-err" className="text-error text-sm">{errors.name.message}</span>}</div>
        <div className="fieldset min-w-0 gap-2 p-0 text-sm"><label className="label whitespace-normal font-medium text-base-content" htmlFor="projects-slug">Slug</label><input id="projects-slug" className={`input w-full ${errors.slug ? "input-error" : "border-(--border-interactive)"}`} {...slugField} aria-invalid={!!errors.slug} aria-describedby={errors.slug ? "slug-help slug-err" : "slug-help"} autoCapitalize="none" maxLength={64} placeholder="commercial-loan-onboarding" spellCheck={false} /><span id="slug-help" className="text-caption text-secondary">Generated from the name. You can edit it before creating the project.</span>{errors.slug && <span id="slug-err" className="text-error text-sm">{errors.slug.message}</span>}</div>
        <div className="fieldset min-w-0 gap-2 p-0 text-sm"><label className="label whitespace-normal font-medium text-base-content" htmlFor="projects-description">Description</label><input id="projects-description" className="input border-(--border-interactive) w-full" {...register("description")} /></div>
        <div className="lg:col-span-3"><AsyncButton type="submit" className="btn btn-primary" pending={isSubmitting || create.isPending} pendingLabel="Creating…">Create project</AsyncButton></div>
      </form>}
      <TableSearch id="projects-search" className="mb-3 max-w-sm" value={search} onChange={setSearch} placeholder="Name, slug, or description" />
      <DataTable<Project> caption="Projects" data={q.data} isLoading={q.isLoading} isFetching={q.isFetching} error={q.error as Error} onRetry={() => q.refetch()} state={state} update={update} getRowId={(r) => r.id}
        onRowOpen={(p) => { usePrefs.getState().setContext(p.id, null); toast(`Active project: ${p.name}`); }}
        columns={[{ id: "name", header: "Name", accessorKey: "name" }, { id: "slug", header: "Slug", accessorKey: "slug", cell: (c) => <span className="font-mono">{c.getValue<string>()}</span> },
                  { id: "description", header: "Description", accessorKey: "description", enableSorting: false }, { id: "created", header: "Created", accessorKey: "created", cell: (c) => fmtDate(c.getValue<string>()) }]} />
    </div>
  );
}
