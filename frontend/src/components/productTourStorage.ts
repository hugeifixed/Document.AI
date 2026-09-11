const TOUR_VERSION = "1";

export function productTourStorageKey(username: string) {
  return `docai-product-tour:${TOUR_VERSION}:${encodeURIComponent(username)}`;
}

export function hasAcknowledgedProductTour(username: string) {
  try {
    return localStorage.getItem(productTourStorageKey(username)) === "acknowledged";
  } catch {
    return false;
  }
}

export function acknowledgeProductTour(username: string) {
  try {
    localStorage.setItem(productTourStorageKey(username), "acknowledged");
  } catch {
    /* Storage can be unavailable; the tour still remains usable. */
  }
}
