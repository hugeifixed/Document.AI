import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AxiosError, type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { useEffect } from "react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { get, http, isAuthenticationError } from "@/api/client";
import type { Me } from "@/api/types";
import { safeReturnPath } from "@/auth/redirect";
import { RequireSession, SessionProvider, useSession } from "@/auth/Session";
import { Login } from "@/pages/Login";
import { useWorkingContext } from "@/workspace/context";

const profile: Me = { username: "reviewer", is_staff: false, roles: ["docai_reviewers"], platform_version: "1", adapters: { layout: "mock", llm: "mock", task_runner: "sync" }, tools: { request_profiler: null } };
const originalAdapter = http.defaults.adapter;
let user: Me | null;
let requests: string[];
let failPrivate: "expired" | "forbidden" | null;

function reject(config: InternalAxiosRequestConfig, status: number, code: string) {
  const response = { status, data: { success: false, error_code: code, message: code }, headers: {}, statusText: "error", config };
  return Promise.reject(new AxiosError("Request failed", "ERR_BAD_REQUEST", config, undefined, response));
}

beforeEach(() => {
  user = null;
  requests = [];
  failPrivate = null;
  const adapter: AxiosAdapter = async (config) => {
    requests.push(`${config.method} ${config.url}`);
    if (config.url === "/auth/login/") {
      if (JSON.parse(config.data).password !== "correct") return reject(config, 400, "INVALID_CREDENTIALS");
      user = profile;
    }
    if (config.url === "/auth/logout/") user = null;
    if (config.url === "/private/" && failPrivate) return reject(config, 403, failPrivate === "expired" ? "NOT_AUTHENTICATED" : "PERMISSION_DENIED");
    return { status: 200, data: { success: true, data: { user } }, headers: {}, statusText: "OK", config } as AxiosResponse;
  };
  http.defaults.adapter = adapter;
});
afterEach(() => { cleanup(); http.defaults.adapter = originalAdapter; });

function PrivatePage() {
  const session = useSession();
  return <><h1>Private workspace</h1><button onClick={() => void session.signOut()}>Log out</button></>;
}

function setup(path = "/results?run=123") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = { state: { location: { pathname: "", search: "" } }, navigate: (_path: string) => {} };
  function LocationProbe() {
    const location = useLocation();
    const navigate = useNavigate();
    useEffect(() => { router.state.location = location; router.navigate = navigate; }, [location, navigate]);
    return null;
  }
  render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}>
    <LocationProbe />
    <Routes><Route element={<SessionProvider />}>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireSession />}><Route path="*" element={<PrivatePage />} /></Route>
    </Route></Routes>
  </MemoryRouter></QueryClientProvider>);
  return { qc, router };
}

async function signIn(password = "correct") {
  fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "reviewer" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

it("gates private pages, returns to the requested URL, and clears data on login and logout", async () => {
  const { qc, router } = setup();
  await screen.findByRole("heading", { name: "Sign in to DocAI" });
  expect(screen.queryByText("Private workspace")).not.toBeInTheDocument();
  expect(requests.every((request) => request === "get /auth/session/")).toBe(true);
  qc.setQueryData(["previous-user"], "private");
  useWorkingContext.setState({ projectId: "previous-project", datasetId: "previous-dataset" });
  await signIn();
  await screen.findByText("Private workspace");
  expect(router.state.location.pathname + router.state.location.search).toBe("/results?run=123");
  expect(qc.getQueryData(["previous-user"])).toBeUndefined();
  expect(useWorkingContext.getState()).toMatchObject({ projectId: null, datasetId: null });
  qc.setQueryData(["private-documents"], ["secret"]);
  useWorkingContext.setState({ projectId: "project-1", datasetId: "dataset-1" });
  fireEvent.click(screen.getByRole("button", { name: "Log out" }));
  await screen.findByRole("heading", { name: "Sign in to DocAI" });
  expect(requests).toContain("post /auth/logout/");
  expect(qc.getQueryData(["private-documents"])).toBeUndefined();
  expect(useWorkingContext.getState()).toMatchObject({ projectId: null, datasetId: null });
  await act(async () => { await router.navigate("/results"); });
  await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
  expect(screen.queryByText("Private workspace")).not.toBeInTheDocument();
});

it("keeps invalid credentials on the login form with an accessible error", async () => {
  setup();
  await signIn("wrong");
  expect(await screen.findByRole("alert")).toHaveTextContent("Username or password is incorrect");
  expect(screen.getByLabelText("Password")).toHaveValue("");
  expect(screen.getByLabelText("Username")).toHaveValue("reviewer");
  expect(screen.queryByText("Private workspace")).not.toBeInTheDocument();
});

it("identifies missing credentials before sending a login request", async () => {
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "Sign in" }));
  await screen.findByText("Enter your username.");
  expect(screen.getByText("Enter your password.")).toBeInTheDocument();
  expect(screen.getByLabelText("Username")).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByLabelText("Password")).toHaveAttribute("aria-invalid", "true");
  expect(requests).not.toContain("post /auth/login/");
});

it("redirects expired sessions centrally but preserves genuine permission errors", async () => {
  user = profile;
  const { router } = setup();
  await screen.findByText("Private workspace");
  failPrivate = "forbidden";
  await act(async () => { await expect(get("/private/")).rejects.toSatisfy((error: unknown) => !isAuthenticationError(error)); });
  expect(screen.getByText("Private workspace")).toBeInTheDocument();
  failPrivate = "expired";
  await act(async () => { await expect(get("/private/")).rejects.toSatisfy(isAuthenticationError); });
  await screen.findByRole("heading", { name: "Sign in to DocAI" });
  expect(screen.getByText("Your session has ended. Sign in to continue.")).toHaveRole("status");
  expect(router.state.location.search).toContain("next=%2Fresults%3Frun%3D123");
});

it.each(["https://evil.example", "//evil.example", "/\\evil.example", "/login?next=/login", "/api/v1/auth/logout/", "/admin/", "/results/../login"])("rejects unsafe return destination %s", (path) => {
  expect(safeReturnPath(path)).toBe("/");
});

it("preserves local paths, query strings, and fragments", () => {
  expect(safeReturnPath("/results?run=123#fields")).toBe("/results?run=123#fields");
});
