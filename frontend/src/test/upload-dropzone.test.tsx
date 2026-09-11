import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UploadDropzone } from "@/components/UploadDropzone";

const { postUpload, requestCanceled } = vi.hoisted(() => ({ postUpload: vi.fn(), requestCanceled: vi.fn() }));

vi.mock("@/api/client", () => ({
  ApiError: class extends Error {
    code = "REQUEST_FAILED";
  },
  http: { post: postUpload },
  isRequestCanceled: requestCanceled,
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/a11y/announce", () => ({ announce: vi.fn() }));

function acceptedResponse(name: string, id: string) {
  return {
    status: 201,
    data: {
      success: true,
      message: "accepted",
      trace_id: "trace",
      data: {
        accepted: [{ id, original_filename: name }],
        rejected: [],
      },
    },
  };
}

describe("UploadDropzone", () => {
  beforeEach(() => {
    postUpload.mockReset();
    requestCanceled
      .mockReset()
      .mockImplementation((error: unknown) => error instanceof DOMException && error.name === "AbortError");
  });

  it("queues files for review and uploads at most two concurrently", async () => {
    const user = userEvent.setup();
    let activeRequests = 0;
    let maximumConcurrency = 0;
    postUpload.mockImplementation(async () => {
      activeRequests += 1;
      maximumConcurrency = Math.max(maximumConcurrency, activeRequests);
      await new Promise((resolve) => window.setTimeout(resolve, 10));
      activeRequests -= 1;
      return acceptedResponse(`file-${postUpload.mock.calls.length}.txt`, String(postUpload.mock.calls.length));
    });
    const done = vi.fn();
    render(<UploadDropzone datasetId="dataset-1" onDone={done} />);

    const files = [
      new File(["one"], "one.txt", { type: "text/plain", lastModified: 1 }),
      new File(["two"], "two.txt", { type: "text/plain", lastModified: 2 }),
      new File(["three"], "three.txt", { type: "text/plain", lastModified: 3 }),
    ];
    await user.upload(screen.getByLabelText("Choose documents"), files);

    expect(await screen.findByText("one.txt")).toBeInTheDocument();
    expect(screen.getByText("three.txt")).toBeInTheDocument();
    expect(postUpload).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Upload 3 files" }));
    await waitFor(() => expect(done).toHaveBeenCalledTimes(1));
    expect(postUpload).toHaveBeenCalledTimes(3);
    expect(maximumConcurrency).toBe(2);
    expect(screen.getAllByText(/Accepted$/)).toHaveLength(3);
  });

  it("starts a queued file only once when the upload action is clicked rapidly", async () => {
    const user = userEvent.setup();
    let finishUpload!: (value: ReturnType<typeof acceptedResponse>) => void;
    postUpload.mockReturnValue(new Promise((resolve) => { finishUpload = resolve; }));
    const done = vi.fn();
    render(<UploadDropzone datasetId="dataset-1" onDone={done} />);

    await user.upload(screen.getByLabelText("Choose documents"), new File(["one"], "one.txt", { type: "text/plain" }));
    const upload = await screen.findByRole("button", { name: "Upload 1 file" });
    upload.click();
    upload.click();

    await waitFor(() => expect(postUpload).toHaveBeenCalledTimes(1));
    finishUpload(acceptedResponse("one.txt", "document-1"));
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
  });

  it("shows react-dropzone validation errors before any network request", async () => {
    const user = userEvent.setup();
    render(<UploadDropzone datasetId="dataset-1" onDone={() => {}} maxMb={1} />);
    const tooLarge = new File([new Uint8Array(1_048_577)], "large.pdf", {
      type: "application/pdf",
      lastModified: 1,
    });

    await user.upload(screen.getByLabelText("Choose documents"), tooLarge);

    expect(await screen.findByText("File is larger than the configured limit.")).toBeInTheDocument();
    expect(screen.getByText("FILE_TOO_LARGE")).toBeInTheDocument();
    expect(postUpload).not.toHaveBeenCalled();
  });

  it("clears queued files when the selected dataset changes", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<UploadDropzone datasetId="dataset-1" onDone={() => {}} />);
    const file = new File(["one"], "one.txt", { type: "text/plain", lastModified: 1 });
    await user.upload(screen.getByLabelText("Choose documents"), file);
    expect(await screen.findByText("one.txt")).toBeInTheDocument();

    rerender(<UploadDropzone datasetId="dataset-2" onDone={() => {}} />);

    await waitFor(() => expect(screen.queryByText("one.txt")).not.toBeInTheDocument());
    expect(postUpload).not.toHaveBeenCalled();
  });

  it("paginates large queues so only the current group is rendered", async () => {
    const user = userEvent.setup();
    render(<UploadDropzone datasetId="dataset-1" onDone={() => {}} />);
    const files = Array.from(
      { length: 51 },
      (_, index) => new File([String(index)], `document-${index + 1}.txt`, { type: "text/plain", lastModified: index }),
    );

    await user.upload(screen.getByLabelText("Choose documents"), files);

    expect(await screen.findByText("document-1.txt")).toBeInTheDocument();
    expect(screen.queryByText("document-51.txt")).not.toBeInTheDocument();
    expect(screen.getByText("Showing 1–50 of 51")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("document-51.txt")).toBeInTheDocument();
    expect(screen.queryByText("document-1.txt")).not.toBeInTheDocument();
  });

  it("aborts active requests and keeps cancelled files available for retry", async () => {
    const user = userEvent.setup();
    let uploadSignal: AbortSignal | undefined;
    postUpload.mockImplementation(
      (_url: string, _form: FormData, config: { signal: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          uploadSignal = config.signal;
          config.signal.addEventListener("abort", () => reject(new DOMException("Cancelled", "AbortError")));
        }),
    );
    const done = vi.fn();
    render(<UploadDropzone datasetId="dataset-1" onDone={done} />);

    await user.upload(screen.getByLabelText("Choose documents"), new File(["one"], "one.txt", { type: "text/plain" }));
    await user.click(screen.getByRole("button", { name: "Upload 1 file" }));
    await user.click(await screen.findByRole("button", { name: "Cancel uploads" }));

    expect(uploadSignal?.aborted).toBe(true);
    expect(await screen.findByText(/Cancelled$/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry 1 file" })).toBeEnabled();
    expect(done).not.toHaveBeenCalled();
  });

  it("retries an independently failed upload", async () => {
    const user = userEvent.setup();
    const done = vi.fn();
    postUpload.mockRejectedValueOnce(new Error("Connection interrupted"));
    postUpload.mockResolvedValueOnce(acceptedResponse("one.txt", "document-1"));
    render(<UploadDropzone datasetId="dataset-1" onDone={done} />);

    await user.upload(screen.getByLabelText("Choose documents"), new File(["one"], "one.txt", { type: "text/plain" }));
    await user.click(screen.getByRole("button", { name: "Upload 1 file" }));
    expect(await screen.findByText("Connection interrupted")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry 1 file" }));
    await waitFor(() => expect(done).toHaveBeenCalledOnce());
    expect(screen.getByText(/Accepted$/)).toBeInTheDocument();
    expect(postUpload).toHaveBeenCalledTimes(2);
  });

  it("shows a server rejection without treating it as an accepted document", async () => {
    const user = userEvent.setup();
    const done = vi.fn();
    postUpload.mockResolvedValue({
      status: 422,
      data: {
        success: true,
        message: "rejected",
        trace_id: "trace",
        data: {
          accepted: [],
          rejected: [{ filename: "bad.txt", message: "The document is empty.", error_code: "EMPTY_FILE" }],
        },
      },
    });
    render(<UploadDropzone datasetId="dataset-1" onDone={done} />);

    await user.upload(screen.getByLabelText("Choose documents"), new File(["bad"], "bad.txt", { type: "text/plain" }));
    await user.click(screen.getByRole("button", { name: "Upload 1 file" }));

    expect(await screen.findByText("The document is empty.")).toBeInTheDocument();
    expect(screen.getByText("EMPTY_FILE")).toBeInTheDocument();
    expect(screen.getByText(/Rejected$/)).toBeInTheDocument();
    expect(done).not.toHaveBeenCalled();
  });
});
