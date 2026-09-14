/** Collection display is driven by field type, never business field names. */
export function parseListValue(value: string | null): unknown[] | null {
  if (value == null) return null;
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function listSummary(value: string | null): string {
  if (value == null) return "Not found";
  const entries = parseListValue(value);
  return entries ? `${entries.length} ${entries.length === 1 ? "entry" : "entries"}` : "List needs checking";
}
