import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ProcessingProgress, Progress } from "@/api/types";
import { RunProgress } from "@/components/RunProgress";
import { estimateLabel, humanDuration, operationLabel, progressTime, since } from "@/runs/progress";
import { testRun, testRunItem } from "@/test/fixtures";

const { announce } = vi.hoisted(() => ({ announce: vi.fn() }));
vi.mock("@/a11y/announce", () => ({ announce }));
const time = Date.parse("2026-09-13T12:00:00Z");
const iso = (offset = 0) => new Date(time + offset).toISOString();
const snapshot = (patch: Partial<ProcessingProgress> = {}): ProcessingProgress => ({
  phase: "reading_document",
  operation: "waiting_for_ocr",
  phase_started_at: iso(-20_000),
  operation_started_at: iso(-10_000),
  completed_phases: [],
  counter: null,
  segment: null,
  retry_at: null,
  ...patch,
});
const item = testRunItem({ status: "running", progress_updated_at: iso(-10_000), processing_progress: snapshot() });
const progress = (patch: Partial<Progress> = {}): Progress => ({
  total: 10,
  succeeded: 3,
  failed: 0,
  skipped: 0,
  running: 1,
  queued: 6,
  remaining: 7,
  stage: "processing",
  as_of: iso(),
  estimated_finish_at: iso(60_000),
  estimated_seconds_remaining: 60,
  last_milestone_at: iso(-10_000),
  activity_items: [item],
  ...patch,
});
const run = testRun({ total_items: 10, started_at: iso(-60_000), created: iso(-70_000) });
function props() {
  return {
    run,
    progress: progress(),
    receipt: { serverTime: time, monotonicTime: performance.now() },
    selectedFilter: "",
    onFilter: vi.fn(),
    onRefresh: vi.fn(),
    refreshing: false,
    error: false,
  };
}
function view(properties = props()) {
  const result = render(
    <MemoryRouter>
      <RunProgress {...properties} />
    </MemoryRouter>,
  );
  return {
    ...result,
    update: (next: typeof properties) =>
      result.rerender(
        <MemoryRouter>
          <RunProgress {...next} />
        </MemoryRouter>,
      ),
  };
}
beforeEach(() => {
  announce.mockClear();
});
afterEach(() => {
  vi.useRealTimers();
});

it("advances server time with a monotonic clock despite browser wall-clock skew", () => {
  expect(progressTime({ serverTime: time, monotonicTime: 100 }, 2100)).toBe(time + 2000);
  expect(progressTime({ serverTime: NaN, monotonicTime: 100 }, 2100)).toBeNull();
  expect(progressTime(null, 10)).toBeNull();
  expect(since("bad date", time)).toBeNull();
  expect(humanDuration(-100)).toBe("0s");
  expect(humanDuration(3_725_000)).toBe("1h 2m");
});

it("shows elapsed and an honest wait for unknown provider progress without a document percentage", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "performance", "Date"] });
  vi.setSystemTime(new Date("2040-01-01"));
  view();
  expect(screen.getByText("1m 0s elapsed")).toBeVisible();
  expect(screen.getByText("10s elapsed")).toBeVisible();
  expect(screen.getByText(/page completion is not reported/)).toBeVisible();
  expect(screen.getAllByRole("progressbar")).toHaveLength(1);
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "3");
  await act(async () => {
    vi.advanceTimersByTime(3000);
  });
  expect(screen.getByText("13s elapsed")).toBeVisible();
  expect(announce).not.toHaveBeenCalled();
});

it("retains the snapshot during interrupted refreshes, hides ETA, and recovers without closing details", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "performance"] });
  const initial = props();
  const { update } = view(initial);
  const summary = screen.getByLabelText("Processing details for statement.txt");
  fireEvent.click(summary);
  summary.focus();
  expect(summary.closest("details")).toHaveAttribute("open");
  await act(async () => {
    vi.advanceTimersByTime(15_000);
  });
  expect(screen.getByText("Updates interrupted")).toBeVisible();
  expect(screen.queryByText(/About .* remaining/)).not.toBeInTheDocument();
  expect(screen.getByText("3/10 documents completed")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Retry refresh" }));
  expect(initial.onRefresh).toHaveBeenCalledTimes(1);
  update({ ...initial, receipt: { serverTime: time + 15_000, monotonicTime: performance.now() } });
  expect(screen.queryByText("Updates interrupted")).not.toBeInTheDocument();
  expect(summary.closest("details")).toHaveAttribute("open");
  expect(summary).toHaveFocus();
  expect(announce.mock.calls.map(([text]) => text)).toEqual([
    "Progress updates interrupted.",
    "Progress updates restored.",
  ]);
});

it("flags missing milestones without diagnosing workers and resets counters when a group changes", () => {
  const initial = props();
  initial.progress.activity_items = [
    {
      ...item,
      progress_updated_at: iso(-125_000),
      processing_progress: snapshot({
        phase: "analyzing",
        operation: "extracting",
        counter: { completed: 2, total: 3, unit: "chunks" },
        segment: { current: 1, total: 2 },
      }),
    },
  ];
  const { update } = view(initial);
  expect(screen.getByText("No new milestone for 2m 5s · Extracting fields")).toBeVisible();
  expect(screen.getByText("2/3 chunks processed in this group")).toBeVisible();
  const summary = screen.getByLabelText("Processing details for statement.txt");
  fireEvent.click(summary);
  update({
    ...initial,
    progress: progress({
      activity_items: [
        {
          ...item,
          processing_progress: snapshot({
            phase: "analyzing",
            operation: "extracting",
            counter: { completed: 0, total: 2, unit: "chunks" },
            segment: { current: 2, total: 2 },
          }),
        },
      ],
    }),
  });
  expect(screen.getByText("Group 2 of 2")).toBeVisible();
  expect(screen.getByText("0/2 chunks processed in this group")).toBeVisible();
  expect(summary.closest("details")).toHaveAttribute("open");
});

it("shows only applicable phases, real normalization counts and bounded activity", () => {
  const initial = props();
  const preparing = {
    ...item,
    processing_progress: snapshot({
      phase: "preparing_scans",
      operation: "preparing_scans",
      counter: { completed: 1, total: 4, unit: "pages" },
    }),
  };
  initial.progress.activity_items = [
    preparing,
    ...Array.from({ length: 6 }, (_, index) => ({
      ...item,
      id: `item-${index + 2}`,
      document_name: `file-${index}.pdf`,
    })),
  ];
  view(initial);
  expect(screen.getAllByText("Processing details")).toHaveLength(5);
  expect(screen.getByText("1/4 pages examined")).toBeVisible();
  fireEvent.click(screen.getByLabelText("Processing details for statement.txt"));
  expect(screen.getByText("Prepare scans")).toBeVisible();
  expect(screen.getAllByText("Read document")[0]).toBeVisible();
  expect(screen.getAllByText("Analyze")[0]).toBeVisible();
  expect(screen.getAllByText("Save results")[0]).toBeVisible();
});

it.each(["adaptive", "off"])("reads queued preparation mode %s from the serialized run config", (mode) => {
  const initial = props();
  initial.run = testRun({
    config_snapshot: {
      workflow: { name: "scan-test", type: "extract_structured", version: 1 },
      config: { mode: "default", input_quality: { mode } },
      adapters: { layout: "azure_di", llm: "mock" },
      prompts: {},
      schemas: {},
      template: null,
    },
  });
  initial.progress.activity_items = [
    {
      ...item,
      status: "queued",
      input_quality: {},
      processing_progress: snapshot({ phase: "queued", operation: "queued" }),
    },
  ];
  view(initial);
  fireEvent.click(screen.getByLabelText("Processing details for statement.txt"));
  if (mode === "adaptive") expect(screen.getByText("Prepare scans")).toBeVisible();
  else expect(screen.queryByText("Prepare scans")).not.toBeInTheDocument();
});

it("handles legacy and queued items safely and keeps retry scheduling explicit", () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "performance"] });
  const initial = props();
  initial.progress.activity_items = [
    { ...item, status: "queued", processing_progress: null, progress_updated_at: null },
  ];
  const { update } = view(initial);
  expect(screen.getByText("Waiting for a worker (busy or unavailable)")).toBeVisible();
  fireEvent.click(screen.getByLabelText("Processing details for statement.txt"));
  expect(screen.getByText("Detailed milestones are unavailable for this document.")).toBeVisible();
  update({
    ...initial,
    progress: progress({
      activity_items: [
        { ...item, attempts: 2, processing_progress: snapshot({ operation: "retry_wait", retry_at: iso(20_000) }) },
      ],
    }),
  });
  expect(screen.getByText("Waiting to retry")).toBeVisible();
  expect(screen.getByText("Retry scheduled in 20s")).toBeVisible();
  expect(screen.queryByText(/remaining/)).not.toBeInTheDocument();
  expect(operationLabel(testRunItem({ status: "running", stage: "normalization" }))).toBe("Preparing scans");
  expect(operationLabel(testRunItem({ status: "running", stage: "layout" }))).toBe("Reading document");
  expect(operationLabel(testRunItem({ status: "running", stage: "workflow" }))).toBe("Processing document");
  expect(operationLabel(testRunItem({ status: "skipped" }))).toBe("Skipped");
});

it("filters from aggregate counts and makes terminal summaries compact", () => {
  const initial = props();
  const { update } = view(initial);
  fireEvent.click(screen.getByRole("button", { name: "Completed 3" }));
  expect(initial.onFilter).toHaveBeenLastCalledWith("succeeded,failed,skipped");
  fireEvent.click(screen.getByRole("button", { name: "View all active documents" }));
  expect(initial.onFilter).toHaveBeenLastCalledWith("running,queued", true);
  update({
    ...initial,
    run: { ...run, status: "partial", finished_at: iso(60_000) },
    progress: progress({ succeeded: 8, failed: 1, skipped: 1, remaining: 0 }),
  });
  expect(screen.getByRole("heading", { name: "Run summary" })).toBeVisible();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Current activity" })).not.toBeInTheDocument();
  expect(screen.getByText("2m 0s elapsed")).toBeVisible();
  expect(
    within(screen.getByRole("group", { name: "Filter documents by status" })).getByRole("button", {
      name: "Completed 10",
    }),
  ).toBeVisible();
});

it("only shows cautious eligible ETA and reports expired estimates without going negative", () => {
  expect(estimateLabel(run, progress(), time, false)).toBe("About 1m 0s remaining");
  expect(estimateLabel(run, progress(), time + 61_000, false)).toBe("Taking longer than the estimate");
  expect(estimateLabel(run, progress({ succeeded: 2, estimated_finish_at: null }), time, false)).toBe(
    "Estimating after more documents finish",
  );
  for (const patch of [
    { total: 3 },
    { remaining: 0 },
    { failed: 1 },
    { skipped: 1 },
    { estimated_finish_at: null },
    { estimated_finish_at: "invalid" },
  ])
    expect(estimateLabel(run, progress(patch), time, false)).toBeNull();
  expect(estimateLabel({ ...run, cancel_requested: true }, progress(), time, false)).toBeNull();
  expect(estimateLabel(run, progress(), time, true)).toBeNull();
  expect(estimateLabel({ ...run, status: "cancelled" }, progress(), time, false)).toBeNull();
});
