import { ArrowDownTrayIcon, ChevronDownIcon } from "@heroicons/react/20/solid";
import { useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { Run } from "@/api/types";
import { Card, PageHeader, ScrollRegion, StatusChip } from "@/components/ui";
import { useRunCollection } from "@/runs/lifecycle";
import { useWorkingContext } from "@/workspace/context";

function ExportMenu({ run }: { run: Run }) {
  const menu = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const menuId = `export-menu-${run.id}`;
  const anchor = `--${menuId}`;

  function close() {
    menu.current?.hidePopover();
  }

  return (
    <>
      <button
        type="button"
        className="btn btn-xs btn-outline"
        popoverTarget={menuId}
        style={{ anchorName: anchor }}
        aria-controls={menuId}
        aria-expanded={open}
        aria-label={`Download ${run.name || run.workflow_name}`}
      >
        <ArrowDownTrayIcon className="size-4" aria-hidden="true" />
        Download
        <ChevronDownIcon
          className={`size-3 motion-safe:transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>
      <ul
        ref={menu}
        id={menuId}
        popover="auto"
        className="dropdown dropdown-end menu elevation-overlay z-50 mt-1 w-40 rounded-box border border-base-300 bg-base-100 p-1 text-base-content"
        style={{ positionAnchor: anchor }}
        aria-label={`Export formats for ${run.name || run.workflow_name}`}
        onToggle={(event) => setOpen(event.currentTarget.matches(":popover-open"))}
      >
        <li>
          <a href={`/api/v1/runs/${run.id}/export/json/`} download onClick={close}>
            JSON package
          </a>
        </li>
        <li>
          <a href={`/api/v1/runs/${run.id}/export/csv/`} download onClick={close}>
            CSV fields
          </a>
        </li>
        <li>
          <a href={`/api/v1/runs/${run.id}/export/xlsx/`} download onClick={close}>
            Excel workbook
          </a>
        </li>
      </ul>
    </>
  );
}

export function Exports() {
  const { projectId, datasetId } = useWorkingContext();
  const [searchParams] = useSearchParams();
  const selectedRunId = searchParams.get("run");
  const runs = useRunCollection({ purpose: "export", projectId, datasetId });
  const orderedRuns = (runs.data?.results ?? [])
    .filter((run) => ["succeeded", "partial", "failed", "cancelled"].includes(run.status) && run.processed_items > 0)
    .sort((left, right) => (left.id === selectedRunId ? -1 : right.id === selectedRunId ? 1 : 0));
  return (
    <div>
      <PageHeader title="Exports">
        Structured JSON (full package with configuration snapshot, ground truth and review history), CSV (fields, UTF-8
        with BOM) and XLSX. Nested values use dotted keys.
      </PageHeader>
      {selectedRunId && orderedRuns.some((run) => run.id === selectedRunId) && (
        <output className="mb-4 block text-sm text-secondary">
          The selected run appears first. Choose the format required by the receiving system.
        </output>
      )}
      <Card flush>
        <ScrollRegion label="Runs available for export">
          <table className="table">
            <caption className="sr-only">Runs available for export</caption>
            <thead>
              <tr>
                <th scope="col">Run</th>
                <th scope="col">Status</th>
                <th scope="col">Items</th>
                <th scope="col">Download</th>
              </tr>
            </thead>
            <tbody>
              {orderedRuns.map((r) => (
                <tr key={r.id} className={r.id === selectedRunId ? "bg-(--color-blue-soft)" : undefined}>
                  <td>
                    {r.name || r.workflow_name}
                    {r.id === selectedRunId && <span className="badge badge-ghost badge-sm ml-2">Selected</span>}
                  </td>
                  <td>
                    <StatusChip status={r.status} />
                  </td>
                  <td className="tabular-nums">
                    {r.processed_items}/{r.total_items}
                  </td>
                  <td>
                    <ExportMenu run={r} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
        {orderedRuns.length === 0 && (
          <p className="px-5 py-4 text-sm text-secondary">
            No completed runs are available to export.{" "}
            <Link className="link link-primary" to="/runs">
              View runs.
            </Link>
          </p>
        )}
      </Card>
    </div>
  );
}
