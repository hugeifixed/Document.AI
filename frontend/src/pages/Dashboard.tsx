import { ArrowDownTrayIcon, ArrowRightIcon, ArrowUpTrayIcon, ClipboardDocumentCheckIcon, ExclamationTriangleIcon, PlayCircleIcon, ShareIcon, TagIcon } from "@heroicons/react/20/solid";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { Dashboard as DashboardData } from "@/api/types";
import { ErrorNotice } from "@/components/ErrorNotice";
import { ActionPill, Card, EmptyState, PageHeader, ScrollRegion, Skeleton, Stat, StatusChip, fmtDate } from "@/components/ui";
import { usePrefs } from "@/store/prefs";

/** Run statuses in the order the hero bar paints them; anything else lands in "other". */
const RUN_SEGMENTS: { key: string; label: string; color: string }[] = [
  { key: "succeeded", label: "Succeeded", color: "var(--color-success)" },
  { key: "running", label: "Processing", color: "var(--color-primary)" },
  { key: "queued", label: "Queued", color: "var(--color-base-300)" },
  { key: "partial", label: "Partial", color: "var(--color-warning)" },
  { key: "failed", label: "Failed", color: "var(--color-error)" },
  { key: "cancelled", label: "Cancelled", color: "var(--color-ink-3)" },
];

const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

export function Dashboard() {
  const { user } = useSession();
  const canReview = !!user?.roles.includes("docai_reviewers");
  const canOperate = !!user?.roles.includes("docai_operators");
  const projectId = usePrefs((s) => s.projectId);
  const q = useQuery({ queryKey: ["dashboard", projectId], queryFn: () => get<DashboardData>("/dashboard/", projectId ? { project: projectId } : undefined), refetchInterval: 15000 });
  const d = q.data;
  const runTotal = d ? Object.values(d.runs).reduce((a, b) => a + b, 0) : 0;
  const running = d?.runs.running ?? 0;
  const known = new Set(RUN_SEGMENTS.map((s) => s.key));
  const other = d ? Object.entries(d.runs).filter(([k]) => !known.has(k)).reduce((a, [, v]) => a + v, 0) : 0;
  const segments = d ? [...RUN_SEGMENTS.map((s) => ({ ...s, count: d.runs[s.key] ?? 0 })), { key: "other", label: "Other", color: "var(--color-base-300)", count: other }].filter((s) => s.count > 0) : [];
  const processed = d ? d.recent_runs.reduce((a, r) => a + r.processed, 0) : 0;
  const summary = d
    ? `${plural(running, "run")} in progress and ${plural(d.review_queue.fields, "field")} waiting for a reviewer. Counts refresh every 15 seconds.`
    : "Health of the platform at a glance. Counts refresh every 15 seconds.";
  return (
    <div>
      <PageHeader title={user ? `Welcome back, ${user.username}` : "Dashboard"}>{summary}</PageHeader>
      <nav aria-label="Quick actions" className="mb-6 flex flex-wrap gap-2">
        {canOperate && <ActionPill to="/runs" primary icon={<PlayCircleIcon className="size-4" aria-hidden="true" />}>Start run</ActionPill>}
        <ActionPill to="/datasets" icon={<ArrowUpTrayIcon className="size-4" aria-hidden="true" />}>Upload documents</ActionPill>
        {canOperate && <ActionPill to="/workflows/new" icon={<ShareIcon className="size-4" aria-hidden="true" />}>New workflow version</ActionPill>}
        {canReview && <ActionPill to="/review" icon={<ClipboardDocumentCheckIcon className="size-4" aria-hidden="true" />}>Review queue</ActionPill>}
        <ActionPill to="/exports" icon={<ArrowDownTrayIcon className="size-4" aria-hidden="true" />}>Export results</ActionPill>
      </nav>
      {q.isLoading && <>
        <output className="sr-only">Loading dashboard…</output>
        <div aria-hidden="true">
          <div className="mb-6 grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <Card><div className="space-y-4 py-2"><Skeleton className="h-4 w-36" /><Skeleton className="h-9 w-24" /><Skeleton className="h-2.5 w-full" /></div></Card>
            <Card title="Review queue"><div className="space-y-5 py-2"><Skeleton className="h-5 w-full" /><Skeleton className="h-5 w-2/3" /></div></Card>
          </div>
          <div className="mb-6 grid grid-cols-2 gap-4 xl:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => <div key={i} className="stats min-w-0 rounded-box border border-base-300 bg-base-100"><div className="stat gap-2 p-4"><Skeleton className="h-4 w-28 max-w-full" /><Skeleton className="h-8 w-12" /><Skeleton className="h-3 w-20 max-w-full" /></div></div>)}
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="Recent runs"><div className="space-y-5 py-2">{Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-5 w-full" />)}</div></Card>
            <Card title="Recent errors"><div className="space-y-5 py-2"><Skeleton className="h-5 w-3/4" /><Skeleton className="h-5 w-1/2" /></div></Card>
          </div>
        </div>
      </>}
      {q.error && <div className="mb-6"><ErrorNotice message={q.error.message} onRetry={() => void q.refetch()} /></div>}
      {d && (<>
        <div className="mb-6 grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <Card>
            <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between sm:gap-8">
              <div className="min-w-0">
                <p className="text-sm font-medium text-secondary">Runs to date</p>
                <p className="mt-1 text-4xl font-semibold leading-none tracking-tight lining-nums tabular-nums">{runTotal.toLocaleString()}</p>
                <p className="mt-2 text-caption text-(--color-ink-3)">{projectId ? "In the active project" : "Across all projects"}</p>
              </div>
              <dl className="w-full divide-y divide-base-300 text-sm sm:w-72 sm:shrink-0">
                <div className="flex items-center justify-between gap-4 py-2"><dt className="text-secondary">Processing now</dt><dd className="font-semibold tabular-nums">{running.toLocaleString()}</dd></div>
                <div className="flex items-center justify-between gap-4 py-2"><dt className="text-secondary">Documents in recent runs</dt><dd className="font-semibold tabular-nums">{processed.toLocaleString()}</dd></div>
              </dl>
            </div>
            {segments.length > 0 ? (
              <div className="mt-6">
                <div className="flex h-2.5 w-full gap-0.5 overflow-hidden rounded-full bg-base-200" aria-hidden="true">
                  {segments.map((s) => <span key={s.key} className="block h-full min-w-1 rounded-full" style={{ width: `${(s.count / runTotal) * 100}%`, background: s.color }} />)}
                </div>
                <ul className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5 text-caption text-secondary" aria-label="Runs by status">
                  {segments.map((s) => <li key={s.key} className="inline-flex items-center gap-1.5 whitespace-nowrap tabular-nums"><span aria-hidden="true" className="inline-block size-2 rounded-full" style={{ background: s.color }} />{s.label} · {s.count.toLocaleString()}</li>)}
                </ul>
              </div>
            ) : <p className="mt-5 text-sm text-secondary">No runs yet. {canOperate ? <Link className="link link-primary" to="/runs">Start the first one.</Link> : "An operator can start the first one."}</p>}
          </Card>
          <Card title="Review queue" action={canReview && <Link className="link link-primary text-sm font-medium" to="/review">Open queue</Link>}>
            <ul className="divide-y divide-base-300">
              <li className="flex items-center gap-3 py-2.5">
                <span aria-hidden="true" className="grid size-8 shrink-0 place-items-center rounded-full bg-(--color-warning-soft) text-warning"><ExclamationTriangleIcon className="size-4" /></span>
                <span className="min-w-0 flex-1"><span className="block text-sm font-medium">Fields needing review</span><span className="block text-caption text-(--color-ink-3)">Low score, missing grounding, validation</span></span>
                <span className="text-base font-semibold tabular-nums">{d.review_queue.fields.toLocaleString()}</span>
              </li>
              <li className="flex items-center gap-3 py-2.5">
                <span aria-hidden="true" className="grid size-8 shrink-0 place-items-center rounded-full bg-(--color-blue-soft) text-primary"><TagIcon className="size-4" /></span>
                <span className="min-w-0 flex-1"><span className="block text-sm font-medium">Classifications</span><span className="block text-caption text-(--color-ink-3)">Disagreement or low confidence</span></span>
                <span className="text-base font-semibold tabular-nums">{d.review_queue.classifications.toLocaleString()}</span>
              </li>
            </ul>
            {canReview && d.review_queue.fields > 0 && (
              <Link to="/review" className="callout-warm mt-4 text-sm">
                <span className="min-w-0 flex-1"><span className="font-semibold text-base-content">{plural(d.review_queue.fields, "field is", "fields are")} waiting.</span> Reviewing in context keeps the queue short.</span>
                <span aria-hidden="true" className="grid size-7 shrink-0 place-items-center rounded-full bg-base-100 elevation-raised"><ArrowRightIcon className="size-4" /></span>
              </Link>
            )}
          </Card>
        </div>
        <div className="mb-6 grid grid-cols-2 gap-4 xl:grid-cols-4">
          <Stat label="Runs in progress" value={running} hint={`${runTotal.toLocaleString()} total`} to="/runs?status=running" />
          <Stat label="Fields awaiting review" value={d.review_queue.fields} hint={`${d.review_queue.classifications.toLocaleString()} classifications`} to={canReview ? "/review" : undefined} />
          <Stat label="Workflow versions" value={d.configurations} hint={`${d.datasets.toLocaleString()} datasets`} to="/configurations" />
          <Stat label="Evaluations" value={d.evaluations} to="/evaluation" />
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <Card title="Recent runs" flush={d.recent_runs.length > 0} action={<Link className="link link-primary text-sm font-medium" to="/runs">View all</Link>}>
            {d.recent_runs.length === 0 ? <EmptyState text="No runs yet." action={canOperate ? <Link className="btn btn-primary btn-sm" to="/runs">Start a run</Link> : undefined} /> : (
              <ScrollRegion label="Recent runs"><table className="table table-sm"><caption className="sr-only">Recent runs</caption><thead><tr><th scope="col">Run</th><th scope="col">Status</th><th scope="col" className="text-end">Progress</th><th scope="col">Created</th></tr></thead>
                <tbody>{d.recent_runs.map((r) => <tr key={r.id}><td className="whitespace-nowrap"><Link className="link link-hover font-medium" to={`/runs/${r.id}`}>{r.name || r.workflow}</Link></td><td><StatusChip status={r.status} /></td><td className="text-end lining-nums tabular-nums">{r.processed}/{r.total}</td><td className="text-secondary">{fmtDate(r.created)}</td></tr>)}</tbody></table></ScrollRegion>)}
          </Card>
          <Card title="Recent errors">
            {d.recent_errors.length === 0 ? <p className="text-sm text-secondary">No failed items.</p> : (
              <ul className="divide-y divide-base-300 text-sm">{d.recent_errors.map((e, i) => <li key={i} className="flex gap-3 py-2.5"><span aria-hidden="true" className="mt-1.5 inline-block size-2 shrink-0 rounded-full bg-error" /><span className="min-w-0"><Link className="link link-hover font-medium" to={`/runs/${e.run_id}`}>{e.document}</Link><span className="block text-secondary">{e.message} <span className="font-mono text-caption text-(--color-ink-3)">{e.code}</span></span></span></li>)}</ul>)}
          </Card>
        </div>
      </>)}
    </div>
  );
}
