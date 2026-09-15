export interface ChartRow {
  label: string;
  values: (number | null)[];
}
export interface ChartSeries {
  label: string;
  color: string;
}
export interface ChartProps {
  title: string;
  description: string;
  rows: ChartRow[];
  series: ChartSeries[];
  unit?: string;
}
export const chartColors = [
  "var(--color-primary)",
  "var(--color-error)",
  "var(--color-warning)",
  "var(--color-secondary)",
];
export function chartValue(value: number | null, unit = "") {
  return value == null ? "Unknown" : `${value.toLocaleString()}${unit ? ` ${unit}` : ""}`;
}
