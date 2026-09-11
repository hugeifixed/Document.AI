export type Bounds = { left: string; top: string; width: string; height: string };

/** Convert a normalized polygon into the smallest CSS percentage rectangle that contains it. */
export function polygonBounds(polygon: number[]): Bounds | null {
  if (polygon.length < 8) return null;
  const xs = polygon.filter((_, index) => index % 2 === 0);
  const ys = polygon.filter((_, index) => index % 2 === 1);
  return {
    left: `${Math.min(...xs) * 100}%`,
    top: `${Math.min(...ys) * 100}%`,
    width: `${(Math.max(...xs) - Math.min(...xs)) * 100}%`,
    height: `${(Math.max(...ys) - Math.min(...ys)) * 100}%`,
  };
}
