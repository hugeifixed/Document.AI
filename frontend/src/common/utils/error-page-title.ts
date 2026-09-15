export function errorPageTitle(error: unknown) {
  const status = error && typeof error === "object" && "status" in error ? error.status : undefined;
  return status === 403 ? "Access Denied" : status === 404 ? "Page Not Found" : "Page Error";
}
