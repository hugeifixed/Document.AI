/** Polite live region for status messages (4.1.3). Debounced so polling never chatters. */
let region: HTMLElement | null = null; let timer: number | undefined;
export function announce(text: string, assertive = false) {
  if (!region) {
    region = document.createElement("div"); region.className = "sr-only"; region.setAttribute("aria-live", "polite"); region.setAttribute("role", "status");
    document.body.appendChild(region);
  }
  region.setAttribute("aria-live", assertive ? "assertive" : "polite");
  window.clearTimeout(timer);
  const current = window.setTimeout(() => { if (region) { region.textContent = ""; region.textContent = text; } }, 150);
  timer = current;
  // A finished/unmounted action may cancel its own status, never a newer one.
  return () => {
    if (timer !== current) return;
    window.clearTimeout(current);
    if (region) region.textContent = "";
  };
}
