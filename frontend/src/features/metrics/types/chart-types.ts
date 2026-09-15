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
