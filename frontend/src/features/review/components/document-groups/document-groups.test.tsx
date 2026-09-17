import { act, screen, waitFor } from "@testing-library/react";
import { ApiError } from "@/common/api/client";
import { useLocation } from "react-router-dom";
import { renderWithApp } from "@/test/test-utils";
import { DocumentGroups } from "./document-groups";

const { listGroups } = vi.hoisted(() => ({ listGroups: vi.fn() }));
vi.mock("@/common/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/common/api/client")>()),
  list: listGroups,
}));

const group = {
  id: "segment-1",
  run: "run-1",
  document: "doc-1",
  document_name: "bundle.pdf",
  index: 0,
  start_unit: 0,
  end_unit: 0,
  category: "w2",
  review_status: "auto_accepted",
};
const page = (results = [group], count = results.length) => ({ results, count });

beforeEach(() => {
  listGroups.mockReset();
});

it("distinguishes consecutive W-2 instances and locates the selected page", async () => {
  listGroups.mockResolvedValue(page([group, { ...group, id: "segment-2", index: 1, start_unit: 1, end_unit: 1 }]));
  const locate = vi.fn();
  const { user } = renderWithApp(<DocumentGroups filters={{ document: "doc-1", run: "run-1" }} onLocate={locate} />);
  await user.click(await screen.findByText("Identified documents (2)"));
  expect(screen.getByText("w2 · Document 1 · Page 1")).toBeVisible();
  expect(screen.getByText("w2 · Document 2 · Page 2")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Locate document 2" }));
  expect(locate).toHaveBeenCalledWith(1);
});

it("keeps a grouping obligation visible without offering field approval as a fix", async () => {
  listGroups.mockResolvedValue(
    page([
      {
        ...group,
        review_status: "needs_review",
        boundary_review_reasons: ["SEGMENTATION_BOUNDARY_REPAIRED"],
      } as typeof group,
    ]),
  );
  const { user } = renderWithApp(<DocumentGroups filters={{ run: "run-1", project: "p1" }} reviewOnly />);
  await user.click(await screen.findByText("Why and how to resolve"));
  expect(screen.getByText(/proposed page ranges needed correction/)).toBeVisible();
  expect(screen.getByText(/Accepting a field or classification does not approve/)).toBeVisible();
  expect(screen.getByRole("link", { name: "Inspect grouping" })).toHaveAttribute(
    "href",
    "/review/doc-1?run=run-1&from=review",
  );
  expect(listGroups).toHaveBeenCalledWith(
    "/segments/",
    expect.objectContaining({ project: "p1", run: "run-1", review_status: "needs_review" }),
    expect.anything(),
  );
});

it("paginates groups without fetching the entire bundle", async () => {
  listGroups.mockImplementation((_url, params) =>
    Promise.resolve(page([{ ...group, index: params.page === 2 ? 20 : 0 }], 21)),
  );
  const { user } = renderWithApp(<DocumentGroups filters={{ run: "run-1" }} reviewOnly />);
  await user.click(await screen.findByRole("button", { name: "Next groups" }));
  expect(await screen.findByText("w2 · Document 21 · Page 1")).toBeVisible();
  expect(screen.getByRole("button", { name: "Next groups" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Previous groups" }));
  await waitFor(() => expect(screen.getByText("Page 1 of 2")).toBeVisible());
});

it("reports a failed read and retries rather than implying no grouping needs review", async () => {
  listGroups.mockRejectedValueOnce(new Error("offline")).mockResolvedValue(page([], 0));
  const { user } = renderWithApp(<DocumentGroups filters={{ run: "run-1" }} reviewOnly />);
  await user.click(await screen.findByRole("button", { name: "Retry grouping" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Retry grouping" })).not.toBeInTheDocument());
});

it("observes groups published during processing and refreshes once when processing finishes", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    listGroups.mockResolvedValueOnce(page([], 0)).mockResolvedValue(page([group]));
    const { rerender } = renderWithApp(
      <DocumentGroups filters={{ document: "doc-1", run: "run-1" }} itemStatus="running" />,
    );
    await waitFor(() => expect(listGroups).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/Identified documents/)).not.toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    expect(await screen.findByText("Identified documents (1)")).toBeInTheDocument();
    const calls = listGroups.mock.calls.length;
    rerender(<DocumentGroups filters={{ document: "doc-1", run: "run-1" }} itemStatus="succeeded" />);
    await waitFor(() => expect(listGroups).toHaveBeenCalledTimes(calls + 1));
    await act(async () => {
      vi.advanceTimersByTime(9000);
    });
    expect(listGroups).toHaveBeenCalledTimes(calls + 1);
  } finally {
    vi.useRealTimers();
  }
});

it("restores grouping pagination from the URL without replacing field, run or other table pagination", async () => {
  listGroups.mockImplementation((_url, params) =>
    Promise.resolve(page([{ ...group, index: params.page === 2 ? 20 : 0 }], 21)),
  );
  function Address() {
    return <output aria-label="Current address">{useLocation().search}</output>;
  }
  const { user } = renderWithApp(
    <>
      <DocumentGroups filters={{ run: "run-1" }} reviewOnly />
      <Address />
    </>,
    {
      route: "/review/doc-1?run=run-1&field=field-9&page=4&group_page=2",
    },
  );
  expect(await screen.findByText("Page 2 of 2")).toBeVisible();
  expect(listGroups).toHaveBeenCalledWith("/segments/", expect.objectContaining({ page: 2 }), expect.anything());
  await user.click(screen.getByRole("button", { name: "Previous groups" }));
  await waitFor(() =>
    expect(screen.getByLabelText("Current address")).toHaveTextContent("?run=run-1&field=field-9&page=4"),
  );
  expect(screen.getByLabelText("Current address")).not.toHaveTextContent("group_page");
});

it("recovers an invalid deep-linked group page without retrying the same missing page", async () => {
  listGroups.mockImplementation((_url, params) =>
    params.page === 999
      ? Promise.reject(new ApiError(404, { message: "Invalid page." }))
      : Promise.resolve(page([group])),
  );
  function Address() {
    return <output aria-label="Current address">{useLocation().search}</output>;
  }
  renderWithApp(
    <>
      <DocumentGroups filters={{ run: "run-1" }} reviewOnly />
      <Address />
    </>,
    {
      route: "/review?run=run-1&field=field-9&group_page=999",
    },
  );
  expect(await screen.findByText("w2 · Document 1 · Page 1")).toBeVisible();
  expect(listGroups).toHaveBeenCalledTimes(2);
  expect(screen.getByLabelText("Current address")).toHaveTextContent("?run=run-1&field=field-9");
  expect(screen.getByLabelText("Current address")).not.toHaveTextContent("group_page");
  expect(screen.queryByRole("button", { name: "Retry grouping" })).not.toBeInTheDocument();
});
