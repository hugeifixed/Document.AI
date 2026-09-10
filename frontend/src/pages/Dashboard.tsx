import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get } from "@/api/client";
import { useSession } from "@/auth/Session";
import type { Dashboard as DashboardData } from "@/api/types";
import { ErrorNotice } from "@/components/ErrorNotice";
import { Card, EmptyState, PageHeader, ScrollRegion, Skeleton, Stat, StatusChip, fmtDate } from "@/components/ui";
import { usePrefs } from "@/store/prefs";

export function Dashboard() {
  const { user } = useSession();
  const canReview = !!user?.roles.includes("docai_reviewers");
  const projectId = usePrefs((s) => s.projectId);
  const q = useQuery({ queryKey: ["dashboard", projectId], queryFn: () => get<DashboardData>("/dashboard/", projectId ? { project: projectId } : undefined), refetchInterval: 15000 });
  const d = q.data;
  return (
    <div>
      <PageHeader title="Dashboard">Health of the platform at a glance. Counts refresh every 15 seconds.</PageHeader>
      {q.isLoading && <>
        <output className="sr-only">Loading dashboard…</output>
        <div aria-hidden="true">
          <div className="mb-6 grid grid-cols-2 gap-4 xl:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => <div key={i} className="stats min-w-0 border border-base-300 bg-base-100"><div className="stat gap-2 p-4"><Skeleton className="h-4 w-28 max-w-full" /><Skeleton className="h-8 w-12" /><Skeleton className="h-3 w-20 max-w-full" /></div></div>)}
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="Recent runs"><div className="space-y-5 py-2">{Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-5 w-full" />)}</div></Card>
            <Card title="Recent errors"><div className="space-y-5 py-2"><Skeleton className="h-5 w-3/4" /><Skeleton className="h-5 w-1/2" /></div></Card>
          </div>
        </div>
      </>}
      {q.error && <ErrorNotice message={q.error.message} onRetry={() => void q.refetch()} />}
      {d && (<>
        <div className="mb-6 grid grid-cols-2 gap-4 xl:grid-cols-4">
          <Stat label="Runs in progress" value={d.runs.running ?? 0} hint={`${Object.values(d.runs).reduce((a, b) => a + b, 0)} total`} to="/runs?status=running" />
          <Stat label="Fields awaiting review" value={d.review_queue.fields} hint={`${d.review_queue.classifications} classifications`} to={canReview ? "/review" : undefined} />
          <Stat label="Workflow versions" value={d.configurations} hint={`${d.datasets} datasets`} to="/configurations" />
          <Stat label="Evaluations" value={d.evaluations} to="/evaluation" />
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <Card title="Recent runs">
            {d.recent_runs.length === 0 ? <EmptyState text="No runs yet." action={<Link className="btn btn-primary btn-sm" to="/runs">Start a run</Link>} /> : (
              <ScrollRegion label="Recent runs"><table className="table table-sm"><caption className="sr-only">Recent runs</caption><thead><tr><th scope="col">Run</th><th scope="col">Status</th><th scope="col" className="text-end">Progress</th><th scope="col">Created</th></tr></thead>
                <tbody>{d.recent_runs.map((r) => <tr key={r.id}><td><Link className="link link-primary" to={`/runs/${r.id}`}>{r.name || r.workflow}</Link></td><td><StatusChip status={r.status} /></td><td className="text-end lining-nums tabular-nums">{r.processed}/{r.total}</td><td>{fmtDate(r.created)}</td></tr>)}</tbody></table></ScrollRegion>)}
          </Card>
          <Card title="Recent errors">
            {d.recent_errors.length === 0 ? <p className="text-sm text-secondary">No failed items.</p> : (
              <ul className="space-y-2 text-sm">{d.recent_errors.map((e, i) => <li key={i} className="border-l-2 border-error pl-2"><Link className="link" to={`/runs/${e.run_id}`}>{e.document}</Link> — {e.message} <span className="font-mono text-caption">{e.code}</span></li>)}</ul>)}
          </Card>
        </div>
      </>)}
    </div>
  );
}
