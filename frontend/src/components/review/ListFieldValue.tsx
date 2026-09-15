import { useState } from "react";
import { parseListValue } from "@/listValues";

import { ScrollRegion } from "@/common/components/ui/scroll-region/scroll-region";


const display = (value: unknown): string =>
  value === undefined ? "—" : value === null ? "Not found" : typeof value === "string" ? value : JSON.stringify(value);
const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export function ListFieldValue({ value, name }: { value: string | null; name: string }) {
  const [expanded, setExpanded] = useState(false);
  const entries = parseListValue(value);
  if (value == null) return null;
  if (!entries) return <p className="whitespace-pre-wrap text-sm [overflow-wrap:anywhere]">{value}</p>;
  if (!entries.length) return <p className="text-sm text-secondary">No entries returned.</p>;
  const shown = expanded ? entries : entries.slice(0, 3);
  const objects = entries.every(isObject);
  const keys = objects ? [...new Set(entries.flatMap((entry) => Object.keys(entry)))] : [];
  return (
    <div className="min-w-0 space-y-2">
      {objects && keys.length > 0 ? (
        <ScrollRegion label={`${name} entries`} className="max-w-full rounded-field border border-base-300">
          <table className="table table-sm">
            <caption className="sr-only">{name}</caption>
            <thead>
              <tr>
                {keys.map((key) => (
                  <th key={key} scope="col" className="text-secondary">
                    {key.replaceAll("_", " ")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((entry, index) => (
                <tr key={index}>
                  {keys.map((key) => (
                    <td key={key} className="align-top">
                      <div className="min-w-24 max-w-56 whitespace-pre-wrap [overflow-wrap:anywhere]">
                        {display((entry as Record<string, unknown>)[key])}
                      </div>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
      ) : (
        <ol aria-label={`${name} entries`} className="list-inside list-decimal space-y-2 text-sm">
          {shown.map((entry, index) => (
            <li key={index} className="whitespace-pre-wrap [overflow-wrap:anywhere]">
              {display(entry)}
            </li>
          ))}
        </ol>
      )}
      {entries.length > 3 && (
        <button
          type="button"
          className="btn btn-ghost btn-sm min-h-11 sm:min-h-10"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Show fewer entries" : `Show all ${entries.length} entries`}
        </button>
      )}
    </div>
  );
}
