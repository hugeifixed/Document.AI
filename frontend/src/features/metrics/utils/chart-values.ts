export const chartColors = [
  "var(--color-primary)",
  "var(--color-error)",
  "var(--color-warning)",
  "var(--color-secondary)",
];
export function chartValue(value: number | null, unit = "") {
  return value == null ? "Unknown" : `${value.toLocaleString()}${unit ? ` ${unit}` : ""}`;
}
