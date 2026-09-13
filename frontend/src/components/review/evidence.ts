export type EvidenceRequest = {
  id: number;
  scope: string;
  fieldId: string;
  fieldName: string;
  unit: number | null;
  switchedSource: boolean;
};

/** Only saved, normalized, non-empty geometry can locate evidence. */
export function polygonBounds(polygon: number[]) {
  if (
    polygon.length < 8 ||
    polygon.length % 2 !== 0 ||
    polygon.some((coordinate) => !Number.isFinite(coordinate) || coordinate < 0 || coordinate > 1)
  )
    return null;
  const xs = polygon.filter((_, index) => index % 2 === 0);
  const ys = polygon.filter((_, index) => index % 2 === 1);
  const left = Math.min(...xs);
  const top = Math.min(...ys);
  const width = Math.max(...xs) - left;
  const height = Math.max(...ys) - top;
  if (width <= 0 || height <= 0) return null;
  return { left: `${left * 100}%`, top: `${top * 100}%`, width: `${width * 100}%`, height: `${height * 100}%` };
}
