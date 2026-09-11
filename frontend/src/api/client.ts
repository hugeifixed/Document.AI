/** Axios client that unwraps the API envelope and normalizes errors.
 *  Every error carries error_code + trace_id for support conversations. */
import axios, { AxiosError, type AxiosRequestConfig } from "axios";
import type { Envelope, ErrorDetail, ErrorEnvelope, Page } from "./types";

export class ApiError extends Error {
  code: string;
  traceId: string;
  status: number;
  errors: ErrorDetail[];
  constructor(status: number, body: Partial<ErrorEnvelope> | undefined) {
    super(body?.message || "Request failed.");
    this.status = status;
    this.code = body?.error_code || "REQUEST_FAILED";
    this.traceId = body?.trace_id || "";
    this.errors = body?.errors || [];
  }
}

export const http = axios.create({
  baseURL: "/api/v1",
  withCredentials: true,
  xsrfCookieName: "csrftoken",
  xsrfHeaderName: "X-CSRFToken",
  timeout: 120000,
});

export function isAuthenticationError(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    (error.status === 401 || error.code === "NOT_AUTHENTICATED" || error.code === "AUTHENTICATION_FAILED")
  );
}

export function isRequestCanceled(error: unknown): boolean {
  return axios.isCancel(error);
}

export function apiFieldError(error: unknown, field: string): string | undefined {
  return error instanceof ApiError ? error.errors.find((detail) => detail.field === field)?.message : undefined;
}

export function errorMessage(error: unknown, fallback = "Request failed."): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

const authenticationListeners = new Set<() => void>();
export function onAuthenticationRequired(listener: () => void) {
  authenticationListeners.add(listener);
  return () => {
    authenticationListeners.delete(listener);
  };
}

http.interceptors.response.use(
  (r) => r,
  (err: AxiosError<ErrorEnvelope>) => {
    if (axios.isCancel(err)) return Promise.reject(err);
    const error = new ApiError(err.response?.status ?? 0, err.response?.data);
    if (isAuthenticationError(error) && !err.config?.url?.startsWith("/auth/")) {
      authenticationListeners.forEach((listener) => listener());
    }
    return Promise.reject(error);
  },
);

export async function get<T>(url: string, params?: Record<string, unknown>, config?: AxiosRequestConfig): Promise<T> {
  const r = await http.get<Envelope<T>>(url, { ...config, params });
  return r.data.data;
}
export async function post<T>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const r = await http.post<Envelope<T>>(url, body, config);
  return r.data.data;
}
export async function del(url: string): Promise<void> {
  await http.delete(url);
}
export async function list<T>(
  url: string,
  params: Record<string, unknown>,
  config?: AxiosRequestConfig,
): Promise<Page<T>> {
  return get<Page<T>>(url, params, config);
}

/** Server-side table query params from URL state (page, page_size, ordering, search, filters). */
export function tableParams(s: {
  page: number;
  pageSize: number;
  sort?: string;
  desc?: boolean;
  q?: string;
  filters?: Record<string, string>;
}) {
  const p: Record<string, unknown> = { page: s.page, page_size: s.pageSize, ...(s.filters || {}) };
  if (s.sort) p.ordering = (s.desc ? "-" : "") + s.sort;
  if (s.q) p.search = s.q;
  return p;
}
