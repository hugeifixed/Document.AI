import { useState } from "react";
import { SelectControl } from "@/common/components/ui/select-control/select-control";
export function DateFilter({
  range,
  start,
  end,
  today,
  error,
  onChange,
  validate,
}: {
  range: string;
  start?: string;
  end?: string;
  today: string;
  error?: string;
  onChange: (changes: Record<string, string>) => void;
  validate: (start: string, end: string) => string | undefined;
}) {
  const [draftStart, setDraftStart] = useState(start || today);
  const [draftEnd, setDraftEnd] = useState(end || today);
  const [draftError, setDraftError] = useState<string>();
  return (
    <div className="mb-6 rounded-box border border-base-300 bg-base-100 p-4">
      <div className="flex flex-wrap items-end gap-4">
        <label htmlFor="metrics-range" className="field w-full sm:w-44">
          <span className="label">Date range</span>
          <SelectControl
            id="metrics-range"
            value={range}
            onChange={(e) =>
              onChange({
                range: e.target.value,
                start: e.target.value === "custom" ? draftStart : "",
                end: e.target.value === "custom" ? draftEnd : "",
              })
            }
          >
            <option value="today">Today</option>
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
            <option value="90d">Last 90 days</option>
            <option value="custom">Custom</option>
          </SelectControl>
        </label>
        {range === "custom" && (
          <form
            className="flex min-w-0 flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              const issue = validate(draftStart, draftEnd);
              setDraftError(issue);
              if (!issue) onChange({ start: draftStart, end: draftEnd });
            }}
          >
            <label className="field min-w-0">
              <span className="label">Start date</span>
              <input
                className="input max-w-full"
                type="date"
                value={draftStart}
                max={today}
                onChange={(e) => setDraftStart(e.target.value)}
                required
              />
            </label>
            <label className="field min-w-0">
              <span className="label">End date</span>
              <input
                className="input max-w-full"
                type="date"
                value={draftEnd}
                max={today}
                onChange={(e) => setDraftEnd(e.target.value)}
                required
              />
            </label>
            <button className="btn btn-outline" type="submit">
              Apply dates
            </button>
          </form>
        )}
      </div>
      <p className="mt-3 text-caption text-secondary">
        All dates are inclusive and use UTC. Dates apply to all trends; current review backlog spans all dates.
      </p>
      {(draftError || error) && (
        <p role="alert" className="mt-2 text-sm text-error">
          {draftError || error}
        </p>
      )}
    </div>
  );
}
