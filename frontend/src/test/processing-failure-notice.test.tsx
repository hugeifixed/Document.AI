import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { RunItem } from "@/common/types/api";
import { ProcessingFailureNotice } from "@/components/ProcessingFailureNotice";

const failedItem: RunItem = {
  id: "item-1",
  run: "run-1",
  document: "document-1",
  document_name: "sample.pdf",
  status: "failed",
  stage: "layout",
  attempts: 1,
  error_code: "EMPTY_LAYOUT",
  error_message: "Layout analysis returned no content for this document.",
  retryable: false,
  duration_ms: 42,
  correlation_id: "trace-123",
  processing_progress: null,
  progress_updated_at: null,
  modified: "2026-09-10T00:00:00Z",
};

describe("ProcessingFailureNotice", () => {
  it("explains the document-level failure and links to its run", () => {
    render(
      <MemoryRouter>
        <ProcessingFailureNotice item={failedItem} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("alert")).toHaveAccessibleName("Document processing failed");
    expect(screen.getByText(failedItem.error_message)).toBeVisible();
    expect(screen.getByText("Entire document for this run")).toBeVisible();
    expect(screen.getByText("Layout analysis")).toBeVisible();
    expect(screen.getByText("trace-123")).toBeVisible();
    expect(screen.getByRole("link", { name: "View run" })).toHaveAttribute("href", "/runs/run-1");
  });
});
