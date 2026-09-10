import { useQuery } from "@tanstack/react-query";
import { get } from "@/api/client";
import type { Me } from "@/api/types";
import { Card, PageHeader } from "@/components/ui";
import { type Theme, usePrefs } from "@/store/prefs";

export function Settings() {
  const { theme, setTheme, pageSize, setPageSize } = usePrefs();
  const me = useQuery({ queryKey: ["me"], queryFn: () => get<Me>("/me/") });
  return (
    <div>
      <PageHeader title="Settings" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Appearance">
          <fieldset className="fieldset p-0 text-sm" aria-describedby="theme-help"><legend className="fieldset-legend">Theme</legend>
            <div className="flex flex-wrap gap-4">
              {(["system", "light", "dark"] as Theme[]).map((t) => (
                <label key={t} className="label min-h-8 cursor-pointer gap-2 text-base-content"><input type="radio" name="theme" value={t} className="radio radio-sm" checked={theme === t} onChange={() => setTheme(t)} />{t[0].toUpperCase() + t.slice(1)}</label>))}
            </div>
            <p id="theme-help" className="text-sm text-secondary">System follows your OS preference. Reduced-motion is honored automatically.</p>
          </fieldset>
          <div className="fieldset min-w-0 gap-2 p-0 text-sm mt-4"><label className="label whitespace-normal font-medium text-base-content" htmlFor="settings-page-size">Default rows per page</label><select id="settings-page-size" className="select border-(--border-interactive) select-sm w-32" value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}>{[10, 25, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}</select></div>
        </Card>
        <Card title="Session">
          {me.data && <dl className="grid grid-cols-2 gap-2 text-sm [overflow-wrap:anywhere]"><dt>User</dt><dd>{me.data.username}</dd><dt>Roles</dt><dd>{me.data.roles.join(", ") || "none"}</dd><dt>Platform</dt><dd className="font-mono">{me.data.platform_version}</dd><dt>Layout adapter</dt><dd className="font-mono">{me.data.adapters.layout}</dd><dt>LLM adapter</dt><dd className="font-mono">{me.data.adapters.llm}</dd><dt>Task runner</dt><dd className="font-mono">{me.data.adapters.task_runner}</dd></dl>}
        </Card>
      </div>
    </div>
  );
}
