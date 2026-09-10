import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CorrectionDialog } from "@/components/CorrectionDialog";

describe("CorrectionDialog", () => {
  beforeAll(() => {
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
      configurable: true,
      value(this: HTMLDialogElement) {
        this.setAttribute("open", "");
      },
    });
    Object.defineProperty(HTMLDialogElement.prototype, "close", {
      configurable: true,
      value(this: HTMLDialogElement) {
        this.removeAttribute("open");
        this.dispatchEvent(new Event("close"));
      },
    });
  });

  it("shows field context, edits the existing value, and submits the correction", async () => {
    const confirm = vi.fn();
    render(
      <CorrectionDialog
        fieldName="account holder"
        initialValue="Daniel Silva"
        pending={false}
        onConfirm={confirm}
        onClose={() => {}}
      />,
    );

    expect(await screen.findByRole("dialog", { name: "Correct extracted value" })).toBeVisible();
    expect(screen.getByText("account holder")).toBeInTheDocument();
    const value = screen.getByRole("textbox", { name: "Corrected value" });
    expect(value).toHaveValue("Daniel Silva");

    fireEvent.change(value, { target: { value: "Danielle Silva" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));

    await waitFor(() => expect(confirm).toHaveBeenCalledWith("Danielle Silva"));
  });

  it("closes without submitting when cancelled", async () => {
    const confirm = vi.fn();
    const close = vi.fn();
    render(
      <CorrectionDialog fieldName="total" initialValue="10.00" pending={false} onConfirm={confirm} onClose={close} />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(close).toHaveBeenCalledTimes(1));
    expect(confirm).not.toHaveBeenCalled();
  });
});
