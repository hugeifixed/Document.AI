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

export type EvidenceBounds = NonNullable<ReturnType<typeof polygonBounds>>;
export type EvidenceOverlayPadding = { top: string; right: string; bottom: string; left: string };

function numericBounds(bounds: EvidenceBounds) {
  const left = Number.parseFloat(bounds.left);
  const top = Number.parseFloat(bounds.top);
  const width = Number.parseFloat(bounds.width);
  const height = Number.parseFloat(bounds.height);
  return { left, top, right: left + width, bottom: top + height };
}

function constrainedPadding(gap: number | undefined) {
  if (gap === undefined) return "4px";
  if (gap <= 0) return "0px";
  // Divide nearby whitespace between both overlays and retain a visible gap.
  return `max(0px, min(4px, calc(${gap / 2}% - 1px)))`;
}

/**
 * Add display-only breathing room without expanding neighboring evidence boxes
 * into one another. Provider geometry remains unchanged.
 */
export function evidenceOverlayPadding(bounds: EvidenceBounds, neighbors: EvidenceBounds[]): EvidenceOverlayPadding {
  const current = numericBounds(bounds);
  const centerX = (current.left + current.right) / 2;
  const centerY = (current.top + current.bottom) / 2;
  let topGap: number | undefined;
  let rightGap: number | undefined;
  let bottomGap: number | undefined;
  let leftGap: number | undefined;

  for (const candidate of neighbors) {
    if (candidate === bounds) continue;
    const neighbor = numericBounds(candidate);
    const neighborCenterX = (neighbor.left + neighbor.right) / 2;
    const neighborCenterY = (neighbor.top + neighbor.bottom) / 2;
    const overlapsHorizontally = Math.min(current.right, neighbor.right) > Math.max(current.left, neighbor.left);
    const overlapsVertically = Math.min(current.bottom, neighbor.bottom) > Math.max(current.top, neighbor.top);

    if (overlapsHorizontally && neighborCenterY < centerY) {
      topGap = Math.min(topGap ?? Number.POSITIVE_INFINITY, Math.max(0, current.top - neighbor.bottom));
    }
    if (overlapsHorizontally && neighborCenterY > centerY) {
      bottomGap = Math.min(bottomGap ?? Number.POSITIVE_INFINITY, Math.max(0, neighbor.top - current.bottom));
    }
    if (overlapsVertically && neighborCenterX < centerX) {
      leftGap = Math.min(leftGap ?? Number.POSITIVE_INFINITY, Math.max(0, current.left - neighbor.right));
    }
    if (overlapsVertically && neighborCenterX > centerX) {
      rightGap = Math.min(rightGap ?? Number.POSITIVE_INFINITY, Math.max(0, neighbor.left - current.right));
    }
  }

  return {
    top: constrainedPadding(topGap),
    right: constrainedPadding(rightGap),
    bottom: constrainedPadding(bottomGap),
    left: constrainedPadding(leftGap),
  };
}
