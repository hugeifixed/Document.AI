/** Only return to application pages on this origin after signing in. */
export function safeReturnPath(value: string | null): string {
  if (!value?.startsWith("/") || value.startsWith("//") || /[\\\s]/.test(value)) return "/";
  const url = new URL(value, "https://docai.local");
  if (url.origin !== "https://docai.local" || /^\/(login|admin|api|static|health)(\/|$)/.test(url.pathname)) return "/";
  return url.pathname + url.search + url.hash;
}
