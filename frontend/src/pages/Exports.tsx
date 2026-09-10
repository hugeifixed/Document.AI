import { useQuery } from "@tanstack/react-query";
import { list } from "@/api/client";
import type { Run } from "@/api/types";
import { Card, PageHeader, ScrollRegion, StatusChip } from "@/components/ui";
import { usePrefs } from "@/store/prefs";

export function Exports() {
  const projectId = usePrefs((s) => s.projectId);
  const runs = useQuery({ queryKey: ["runs", projectId, "export"], queryFn: () => list<Run>("/runs/", { page_size: 50, ...(projectId ? { project: projectId } : {}) }) });
  return (
    <div>
      <PageHeader title="Exports">Structured JSON (full package with configuration snapshot, ground truth and review history), CSV (fields, UTF-8 with BOM) and XLSX. Nested values use dotted keys.</PageHeader>
      <Card>
        <ScrollRegion label="Runs available for export"><table className="table"><caption className="sr-only">Runs available for export</caption>
          <thead><tr><th scope="col">Run</th><th scope="col">Status</th><th scope="col">Items</th><th scope="col">Download</th></tr></thead>
          <tbody>{runs.data?.results.map((r) => <tr key={r.id}><td>{r.name || r.workflow_name}</td><td><StatusChip status={r.status} /></td><td className="tabular-nums">{r.processed_items}/{r.total_items}</td>
            <td aria-label={`Download ${r.name || r.workflow_name}`}><div className="flex gap-2"><a className="btn btn-xs btn-outline" href={`/api/v1/runs/${r.id}/export/json/`} download>JSON</a><a className="btn btn-xs btn-outline" href={`/api/v1/runs/${r.id}/export/csv/`} download>CSV</a><a className="btn btn-xs btn-outline" href={`/api/v1/runs/${r.id}/export/xlsx/`} download>XLSX</a></div></td></tr>)}</tbody>
        </table></ScrollRegion>
        {runs.data?.results.length === 0 && <p className="p-4 text-sm">No runs to export yet.</p>}
      </Card>
    </div>
  );
}
