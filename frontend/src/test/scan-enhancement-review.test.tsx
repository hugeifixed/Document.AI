import { act, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { Route, Routes } from "react-router-dom";
import type { Document } from "@/common/types/api";
import { LabelPage } from "@/pages/ReviewWorkspace";
import { ScanEnhancementSummary } from "@/components/ScanEnhancementSummary";
import { page, testDocument, testField, testLabel, testRun, testRunItem } from "@/test/fixtures";
import { renderWithApp, screen } from "@/test/test-utils";

const { getResource, listResource, postResource } = vi.hoisted(() => ({
  getResource: vi.fn(),
  listResource: vi.fn(),
  postResource: vi.fn(),
}));
vi.mock("@/auth/Session", () => ({ useSession: () => ({ user: { roles: ["docai_reviewers"] } }) }));
vi.mock("@/common/api/client", async (original) => ({
  ...(await original<typeof import("@/common/api/client")>()),
  get: getResource,
  list: listResource,
  post: postResource,
}));
vi.mock("@/components/PdfViewer", () => ({
  PdfViewer: ({ file, renderTextLayer, children }: { file: string; renderTextLayer: boolean; children: ReactNode }) => (
    <section aria-label="PDF preview" data-file={file} data-text-layer={renderTextLayer}>
      {children}
    </section>
  ),
}));

it("keeps TIFF-derived PDF evidence aligned with its run and hides it on the original", async () => {
  const runs = [testRun(), testRun({ id: "run-2", name: "Later run" })];
  const document = (run: string): Document =>
    testDocument({
      original_filename: "scanned-statement.tiff",
      file_format: "tiff",
      processing_source: {
        url: `/api/v1/documents/document-1/processing-source/?run=${run}`,
        file_format: "pdf",
        layout_artifact: `layout-${run}`,
        is_original: false,
      },
    });
  let resolveLater!: (doc: Document) => void;
  getResource.mockImplementation((url: string, params: { run?: string }) => {
    if (url.includes("/units/"))
      return Promise.resolve({
        kind: "page",
        index: 0,
        has_text_layer: false,
        width: 612,
        height: 792,
        words: [{ id: `${params.run}:w1`, text: "Account", polygon: [0.1, 0.1, 0.3, 0.1, 0.3, 0.2, 0.1, 0.2] }],
      });
    if (params?.run === "run-2")
      return new Promise<Document>((resolve) => {
        resolveLater = resolve;
      });
    return Promise.resolve(document("run-1"));
  });
  listResource.mockImplementation((url: string) => {
    if (url === "/run-items/")
      return Promise.resolve(page(runs.map((run) => testRunItem({ id: `item-${run.id}`, run: run.id }))));
    if (url === "/runs/") return Promise.resolve(page(runs));
    if (url === "/fields/") return Promise.resolve(page([testField()]));
    return Promise.resolve(page([]));
  });
  postResource.mockResolvedValue(
    testLabel({ is_absent: false, expected_value: "Account", mapping_method: "word_ids" }),
  );
  const { user } = renderWithApp(
    <Routes>
      <Route path="/labeling/:documentId" element={<LabelPage />} />
    </Routes>,
    { route: "/labeling/document-1?run=run-1" },
  );
  expect(await screen.findByRole("region", { name: "PDF preview" })).toHaveAttribute(
    "data-file",
    expect.stringContaining("run=run-1"),
  );
  await user.click(await screen.findByRole("button", { name: "word Account" }));
  expect(screen.getByRole("region", { name: "PDF preview" })).toHaveAttribute("data-text-layer", "false");
  await user.type(screen.getByLabelText(/^Field name/), "account_holder");
  await user.type(screen.getByLabelText("Expected value"), "Account");
  await user.click(screen.getByRole("button", { name: "Save label" }));
  await waitFor(() =>
    expect(postResource).toHaveBeenCalledWith(
      "/labels/",
      expect.objectContaining({ run: "run-1", mode: "word_ids", word_ids: ["run-1:w1"] }),
    ),
  );
  await user.click(screen.getByRole("button", { name: "View original" }));
  expect(screen.queryByRole("button", { name: "word Account" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save label" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Download original TIFF" })).toHaveAttribute(
    "href",
    "/api/v1/documents/document-1/original/",
  );
  await user.selectOptions(screen.getByRole("combobox", { name: "Result version" }), "run-2");
  expect(screen.queryByRole("region", { name: "PDF preview" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save label" })).not.toBeInTheDocument();
  await act(async () => resolveLater(document("run-2")));
  expect(await screen.findByRole("region", { name: "PDF preview" })).toHaveAttribute(
    "data-file",
    expect.stringContaining("run=run-2"),
  );
  expect(await screen.findByRole("button", { name: "word Account" })).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByRole("button", { name: "View original" })).toBeInTheDocument();
  expect(screen.getByLabelText(/^Field name/)).toHaveValue("");
});

it("shows a recoverable page warning without turning success into a failure", async () => {
  const { user } = renderWithApp(
    <ScanEnhancementSummary
      item={testRunItem({
        input_quality: {
          mode: "adaptive",
          status: "fallback",
          profile: "adaptive-v1",
          pages_examined: 4,
          pages_adjusted: 0,
          pages_skipped: 0,
          warnings: [
            {
              code: "NORMALIZATION_FALLBACK",
              message: "Page 4 could not be adjusted. Processing continued with the original page.",
              pages: [4],
              retryable: false,
            },
          ],
        },
      })}
    />,
  );
  expect(screen.getByText("Original used")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  const summary = screen.getByRole("button", { name: /Scan details for/ });
  await user.click(summary);
  expect(screen.getByRole("dialog", { name: "Scan details" })).toBeVisible();
  expect(screen.getByText(/Processing continued with the original page/)).toBeVisible();
  expect(screen.getByText("NORMALIZATION_FALLBACK")).toBeVisible();
});

it("updates the preparation stage quietly when the item completes", () => {
  const { rerender } = renderWithApp(
    <ScanEnhancementSummary item={testRunItem({ status: "running", stage: "normalization" })} />,
  );
  expect(screen.getByText("Preparing scans…")).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  rerender(
    <ScanEnhancementSummary
      item={testRunItem({
        input_quality: {
          mode: "adaptive",
          status: "applied",
          pages_adjusted: 0,
          pages_skipped: 0,
          pages_examined: 1,
          profile: "adaptive-v1",
        },
      })}
    />,
  );
  expect(screen.queryByText("Preparing scans…")).not.toBeInTheDocument();
  expect(screen.getByText("Scans prepared")).toBeInTheDocument();
});

it.each([
  ["workflow", "Layout analysis finished, but the extraction workflow failed."],
  ["layout", "Layout analysis could not be completed."],
])("separates scan preparation from a subsequent %s failure", async (stage, explanation) => {
  const { user } = renderWithApp(
    <ScanEnhancementSummary
      item={testRunItem({
        document_name: "Scanned W2.pdf",
        status: "failed",
        stage,
        error_code: "TEST_PROCESSING_FAILURE",
        error_message: "Check the service configuration before retrying.",
        input_quality: { mode: "adaptive", status: "applied", pages_examined: 2, pages_adjusted: 1, duration_ms: 1875 },
      })}
    />,
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByText("1 page adjusted")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Scan details for Scanned W2.pdf" }));
  expect(screen.getByRole("dialog", { name: "Scan details" })).toBeVisible();
  expect(screen.getByText("Pages examined").parentElement).toHaveTextContent("2");
  expect(screen.getByText("Preparation time").parentElement).toHaveTextContent("1.88 s");
  expect(screen.getByText(explanation)).toBeVisible();
  expect(screen.getByText("Check the service configuration before retrying.")).toBeVisible();
});
