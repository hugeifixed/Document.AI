import { act, fireEvent, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import type { Document, ExtractedField, Span } from "@/api/types";
import { DocumentPage } from "@/pages/ReviewWorkspace";
import { page, testDocument, testField, testRun, testRunItem } from "@/test/fixtures";
import { renderWithApp, screen } from "@/test/test-utils";

const { getResource, listResource, announce, renders } = vi.hoisted(() => ({
  getResource: vi.fn(),
  listResource: vi.fn(),
  announce: vi.fn(() => vi.fn()),
  renders: [] as { pageNumber: number; onRenderSuccess: () => void }[],
}));
vi.mock("@/auth/Session", () => ({ useSession: () => ({ user: { roles: ["docai_reviewers"] } }) }));
vi.mock("@/a11y/announce", () => ({ announce }));
vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  get: getResource,
  list: listResource,
}));
vi.mock("react-pdf", () => ({
  pdfjs: { GlobalWorkerOptions: {} },
  Document: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Page: (props: { pageNumber: number; onRenderSuccess: () => void }) => {
    renders.push(props);
    return <div data-testid="pdf-canvas">Canvas {props.pageNumber}</div>;
  },
}));

const polygon = [0.8, 0.85, 0.95, 0.85, 0.95, 0.9, 0.8, 0.9];
const span = (overrides: Partial<Span> = {}): Span => ({
  id: "span-1",
  unit_index: 1,
  unit_kind: "page",
  text: "Daniel Silva",
  polygon,
  word_ids: [],
  cell_range: "",
  mapping_method: "exact",
  match_score: 1,
  offset_start: null,
  offset_end: null,
  ...overrides,
});
const pdf = (overrides: Partial<Document> = {}): Document =>
  testDocument({
    original_filename: "statement.pdf",
    file_format: "pdf",
    page_count: 2,
    units: [0, 1].map((index) => ({
      id: `unit-${index}`,
      kind: "page",
      index,
      label: `Page ${index + 1}`,
      width: 612,
      height: 792,
      unit: "pt",
    })),
    ...overrides,
  });

function Location() {
  return <output data-testid="location">{useLocation().search}</output>;
}

function setup(document = pdf(), fields = [testField({ spans: [span()] })], query = "", runs = [testRun()]) {
  getResource.mockImplementation((url: string) => {
    const unit = url.match(/\/units\/(\d+)\//)?.[1];
    return Promise.resolve(
      unit ? { kind: "page", index: Number(unit), content: `Content on page ${Number(unit) + 1}` } : document,
    );
  });
  listResource.mockImplementation((url: string) => {
    if (url === "/run-items/") return Promise.resolve(page([testRunItem()]));
    if (url === "/runs/") return Promise.resolve(page(runs));
    if (url === "/fields/") return Promise.resolve(page(fields));
    return Promise.resolve(page([]));
  });
  return renderWithApp(
    <>
      <Location />
      <Routes>
        <Route path="/documents/:documentId" element={<DocumentPage />} />
      </Routes>
    </>,
    {
      route: `/documents/document-1?run=run-1&from=results${query}`,
    },
  );
}

async function completePage(pageNumber: number) {
  await waitFor(() => expect(screen.getByTestId("pdf-canvas")).toHaveTextContent(`Canvas ${pageNumber}`));
  await act(async () =>
    renders
      .filter((render) => render.pageNumber === pageNumber)
      .at(-1)!
      .onRenderSuccess(),
  );
}

let scrolled: { element: Element; options: ScrollIntoViewOptions }[];
beforeEach(() => {
  renders.length = 0;
  scrolled = [];
  announce.mockClear();
  Object.defineProperty(Element.prototype, "scrollIntoView", {
    configurable: true,
    value(this: Element, options: ScrollIntoViewOptions) {
      scrolled.push({ element: this, options });
    },
  });
});

it("locates a deep link after its PDF canvas renders and repeats without letting refetch undo manual navigation", async () => {
  const { user, queryClient } = setup(pdf(), undefined, "&field=field-1");
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Page" })).toHaveValue("1"));
  expect(document.querySelector(".overlay-box.selected")).toBeNull();
  expect(scrolled).toHaveLength(0);
  await completePage(2);
  expect(scrolled).toHaveLength(1);
  expect(scrolled[0].element).toHaveClass("selected", "evidence-emphasis");
  expect(scrolled[0].options).toEqual({ behavior: "smooth", block: "center", inline: "center" });
  expect(announce).toHaveBeenCalledWith("account_holder, page 2.");

  fireEvent.animationEnd(scrolled[0].element);
  expect(scrolled[0].element).toHaveClass("selected");
  expect(scrolled[0].element).not.toHaveClass("evidence-emphasis");
  await user.selectOptions(screen.getByRole("combobox", { name: "Page" }), "0");
  await act(async () =>
    queryClient.setQueryData(["fields", "document-1", "run-1"], page([testField({ spans: [span()], score: 0.95 })])),
  );
  expect(screen.getByRole("combobox", { name: "Page" })).toHaveValue("0");
  expect(scrolled).toHaveLength(1);

  // Return to the previously rendered page before the intervening canvas finishes.
  const stalePage = renders.filter((render) => render.pageNumber === 1).at(-1)!;
  const field = screen.getByRole("button", { name: "account_holder Daniel Silva" });
  await user.click(field);
  await act(async () => stalePage.onRenderSuccess());
  expect(scrolled).toHaveLength(1);
  expect(document.querySelector(".overlay-box.selected")).toBeNull();
  await completePage(2);
  expect(scrolled).toHaveLength(2);
  expect(scrolled[1].element).toHaveClass("evidence-emphasis");
  expect(field).toHaveFocus();
  expect(screen.getByTestId("location")).toHaveTextContent("?run=run-1&from=results&field=field-1");
});

it("cancels a pending location when another field or manual page wins", async () => {
  const fields = [
    testField({ spans: [span()] }),
    testField({ id: "field-2", name: "routing_number", spans: [span({ unit_index: 0 })] }),
  ];
  const { user } = setup(pdf(), fields);
  await completePage(1);
  await user.click(screen.getByRole("button", { name: "account_holder Daniel Silva" }));
  const stalePage = renders.filter((render) => render.pageNumber === 2).at(-1)!;
  await user.click(screen.getByRole("button", { name: "routing_number Daniel Silva" }));
  await act(async () => stalePage.onRenderSuccess());
  expect(scrolled).toHaveLength(0);
  await completePage(1);
  expect(scrolled).toHaveLength(1);
  expect(announce).toHaveBeenLastCalledWith("routing_number, page 1.");
  await user.click(screen.getByRole("button", { name: "account_holder Daniel Silva" }));
  expect(scrolled).toHaveLength(1);
  await user.selectOptions(screen.getByRole("combobox", { name: "Page" }), "0");
  expect(scrolled).toHaveLength(1);
  await completePage(1);
  expect(scrolled).toHaveLength(1);
});

it("keeps keyboard focus while switching incompatible originals to the processing source", async () => {
  const { user } = setup(
    pdf({
      processing_source: {
        url: "/processing.pdf",
        file_format: "pdf",
        layout_artifact: "layout-1",
        is_original: false,
      },
    }),
  );
  await completePage(1);
  await user.click(screen.getByRole("button", { name: "View original" }));
  expect(document.querySelector(".overlay-box")).toBeNull();
  const field = screen.getByRole("button", { name: "account_holder Daniel Silva" });
  field.focus();
  await user.keyboard("{Enter}");
  expect(screen.getByRole("button", { name: "View original" })).toBeInTheDocument();
  expect(scrolled).toHaveLength(0);
  await completePage(2);
  expect(field).toHaveFocus();
  expect(scrolled).toHaveLength(1);
  expect(screen.getByText("Showing evidence on the processing source. account_holder, page 2.")).toBeVisible();
});

it("ignores a previous run's pending canvas after switching result versions", async () => {
  const { user } = setup(pdf(), undefined, "", [testRun(), testRun({ id: "run-2" })]);
  await user.click(await screen.findByRole("button", { name: "account_holder Daniel Silva" }));
  const stalePage = renders.filter((render) => render.pageNumber === 2).at(-1)!;
  await user.selectOptions(await screen.findByRole("combobox", { name: "Result version" }), "run-2");
  await completePage(1);
  await act(async () => stalePage.onRenderSuccess());
  expect(scrolled).toHaveLength(0);
  expect(document.querySelector(".overlay-box.selected")).toBeNull();
  expect(screen.getByTestId("location")).toHaveTextContent("?run=run-2&from=results");
});

it("announces absent geometry without manufacturing a box, including while viewing an original", async () => {
  const fields: ExtractedField[] = [
    testField(),
    testField({
      id: "field-2",
      name: "routing_number",
      spans: [span({ polygon: [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5] })],
    }),
  ];
  const { user } = setup(
    pdf({
      processing_source: {
        url: "/processing.pdf",
        file_format: "pdf",
        layout_artifact: "layout-1",
        is_original: false,
      },
    }),
    fields,
  );
  await completePage(1);
  await user.click(screen.getByRole("button", { name: "View original" }));
  await user.click(screen.getByRole("button", { name: "account_holder Daniel Silva" }));
  expect(screen.getByText("No evidence location is saved for account_holder.")).toBeVisible();
  expect(announce).toHaveBeenLastCalledWith("No evidence location is saved for account_holder.");
  expect(scrolled).toHaveLength(0);
  expect(screen.getByRole("button", { name: "View processing source" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "routing_number Daniel Silva" }));
  await completePage(2);
  expect(screen.getByText(/No bounding box is saved for this field/)).toBeVisible();
  expect(document.querySelector(".overlay-box")).toBeNull();
});

it("uses instant scrolling and a static outline for reduced motion and Space activation", async () => {
  const originalMatchMedia = window.matchMedia;
  vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
    ...originalMatchMedia(query),
    matches: query.includes("prefers-reduced-motion"),
  }));
  const { user } = setup();
  const field = await screen.findByRole("button", { name: "account_holder Daniel Silva" });
  field.focus();
  await user.keyboard(" ");
  await completePage(2);
  expect(scrolled[0].options.behavior).toBe("instant");
  expect(scrolled[0].element).toHaveClass("selected");
  expect(scrolled[0].element).not.toHaveClass("evidence-emphasis");
  expect(field).toHaveFocus();
  vi.mocked(window.matchMedia).mockRestore();
});

it("waits for the current image load, including a zoom while a location is pending", async () => {
  const { user } = setup(pdf({ file_format: "png", original_filename: "statement.png" }), [
    testField({ spans: [span({ unit_index: 0 })] }),
  ]);
  const originalImage = await screen.findByRole("img");
  await user.click(screen.getByRole("button", { name: "account_holder Daniel Silva" }));
  expect(scrolled).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "Zoom in" }));
  fireEvent.load(originalImage);
  expect(scrolled).toHaveLength(0);
  expect(document.querySelector(".overlay-box")).toBeNull();
  fireEvent.load(screen.getByRole("img"));
  await waitFor(() => expect(scrolled).toHaveLength(1));
  expect(scrolled[0].element).toHaveClass("selected");
});

it("still navigates saved pages in text previews", async () => {
  const { user } = setup(pdf({ file_format: "txt", original_filename: "statement.txt" }));
  await user.click(await screen.findByRole("button", { name: "account_holder Daniel Silva" }));
  expect(await screen.findByText("Content on page 2")).toBeVisible();
  await waitFor(() => expect(announce).toHaveBeenCalledWith("account_holder, page 2."));
  expect(screen.queryByText(/No bounding box/)).not.toBeInTheDocument();
});
