import { Card, PageHeader, ScrollRegion, StatusChip } from "@/components/ui";
import { useRunCollection } from "@/runs/lifecycle";
import { useWorkingContext } from "@/workspace/context";

export function Exports() {
  const projectId = useWorkingContext((state) => state.projectId);
  const runs = useRunCollection({ purpose: "export", projectId });
  return (
    <div>
      <PageHeader title="Exports">Structured JSON (full package with configuration snapshot, ground truth and review history), CSV (fields, UTF-8 with BOM) and XLSX. Nested values use dotted keys.</PageHeader>
      <Card flush>
        <ScrollRegion label="Runs available for export"><table className="table"><caption className="sr-only">Runs available for export</caption>
          <thead><tr><th scope="col">Run</th><th scope="col">Status</th><th scope="col">Items</th><th scope="col">Download</th></tr></thead>
          <tbody>{runs.data?.results.map((r) => <tr key={r.id}><td>{r.name || r.workflow_name}</td><td><StatusChip status={r.status} /></td><td className="tabular-nums">{r.processed_items}/{r.total_items}</td>
            <td aria-label={`Download ${r.name || r.workflow_name}`}><div className="flex gap-2"><a className="btn btn-xs btn-outline" href={`/api/v1/runs/${r.id}/export/json/`} download>JSON</a><a className="btn btn-xs btn-outline" href={`/api/v1/runs/${r.id}/export/csv/`} download>CSV</a><a className="btn btn-xs btn-outline" href={`/api/v1/runs/${r.id}/export/xlsx/`} download>XLSX</a></div></td></tr>)}</tbody>
        </table></ScrollRegion>
        {runs.data?.results.length === 0 && <p className="px-5 py-4 text-sm text-secondary">No runs to export yet.</p>}
      </Card>
    </div>
  );
}
