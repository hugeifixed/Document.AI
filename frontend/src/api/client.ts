/** Axios client that unwraps the API envelope and normalizes errors.
 *  Every error carries error_code + trace_id for support conversations. */
import axios, { AxiosError } from "axios";
import type { Envelope, ErrorEnvelope, Page } from "./types";

export class ApiError extends Error {
  code: string; traceId: string; status: number; errors: Record<string, unknown>;
  constructor(status: number, body: Partial<ErrorEnvelope> | undefined) {
    super(body?.message || "Request failed.");
    this.status = status; this.code = body?.error_code || "REQUEST_FAILED"; this.traceId = body?.trace_id || "";
    this.errors = (body?.errors as Record<string, unknown>) || {};
  }
}

export const http = axios.create({ baseURL: "/api/v1", withCredentials: true, xsrfCookieName: "csrftoken", xsrfHeaderName: "X-CSRFToken", timeout: 120000 });

export function isAuthenticationError(error: unknown): error is ApiError {
  return error instanceof ApiError && (error.status === 401 || error.code === "NOT_AUTHENTICATED" || error.code === "AUTHENTICATION_FAILED");
}

const authenticationListeners = new Set<() => void>();
export function onAuthenticationRequired(listener: () => void) {
  authenticationListeners.add(listener);
  return () => { authenticationListeners.delete(listener); };
}

http.interceptors.response.use(
  (r) => r,
  (err: AxiosError<ErrorEnvelope>) => {
    const error = new ApiError(err.response?.status ?? 0, err.response?.data);
    if (isAuthenticationError(error) && !err.config?.url?.startsWith("/auth/")) {
      authenticationListeners.forEach((listener) => listener());
    }
    return Promise.reject(error);
  },
);

export async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const r = await http.get<Envelope<T>>(url, { params });
  return r.data.data;
}
export async function post<T>(url: string, body?: unknown, config?: object): Promise<T> {
  const r = await http.post<Envelope<T>>(url, body, config);
  return r.data.data;
}
export async function del(url: string): Promise<void> { await http.delete(url); }
export async function list<T>(url: string, params: Record<string, unknown>): Promise<Page<T>> { return get<Page<T>>(url, params); }

/** Server-side table query params from URL state (page, page_size, ordering, search, filters). */
export function tableParams(s: { page: number; pageSize: number; sort?: string; desc?: boolean; q?: string; filters?: Record<string, string> }) {
  const p: Record<string, unknown> = { page: s.page, page_size: s.pageSize, ...(s.filters || {}) };
  if (s.sort) p.ordering = (s.desc ? "-" : "") + s.sort;
  if (s.q) p.search = s.q;
  return p;
}
