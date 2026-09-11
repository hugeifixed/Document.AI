import { useQuery } from "@tanstack/react-query";
import { get } from "@/api/client";
import type { Me } from "@/api/types";
import { ErrorNotice } from "@/components/ErrorNotice";
import { Card, Field, PageHeader } from "@/components/ui";
import { type Theme, usePrefs } from "@/store/prefs";

export function Settings() {
  const { theme, setTheme, pageSize, setPageSize } = usePrefs();
  const me = useQuery({ queryKey: ["me"], queryFn: ({ signal }) => get<Me>("/me/", undefined, { signal }) });
  return (
    <div>
      <PageHeader title="Settings" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Appearance">
          <div className="grid gap-5">
          <fieldset className="field" aria-describedby="theme-help"><legend className="label">Theme</legend>
            <div className="flex flex-wrap gap-4">
              {(["system", "light", "dark"] as Theme[]).map((t) => (
                <label key={t} className="label min-h-8 cursor-pointer gap-2 text-base-content"><input type="radio" name="theme" value={t} className="radio radio-sm" checked={theme === t} onChange={() => setTheme(t)} />{t[0].toUpperCase() + t.slice(1)}</label>))}
            </div>
            <p id="theme-help" className="field-help text-sm text-secondary">System follows your OS preference. Reduced-motion is honored automatically.</p>
          </fieldset>
          <Field id="settings-page-size" label="Default rows per page"><select id="settings-page-size" className="select border-(--border-interactive) select-sm w-32" value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}>{[10, 25, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}</select></Field>
          </div>
        </Card>
        <Card title="Session">
          {me.isPending && <output className="inline-flex items-center gap-2 text-sm text-secondary"><span className="loading loading-spinner loading-sm" aria-hidden="true" />Loading session details…</output>}
          {me.error && <ErrorNotice message="Session details could not be loaded." onRetry={() => void me.refetch()} />}
          {me.data && <dl className="grid grid-cols-2 gap-2 text-sm [overflow-wrap:anywhere]"><dt>User</dt><dd>{me.data.username}</dd><dt>Roles</dt><dd>{me.data.roles.join(", ") || "none"}</dd><dt>Platform</dt><dd className="font-mono">{me.data.platform_version}</dd><dt>Layout adapter</dt><dd className="font-mono">{me.data.adapters.layout}</dd><dt>LLM adapter</dt><dd className="font-mono">{me.data.adapters.llm}</dd><dt>Task runner</dt><dd className="font-mono">{me.data.adapters.task_runner}</dd></dl>}
        </Card>
      </div>
    </div>
  );
}
