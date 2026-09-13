import { fireEvent, render, screen } from "@testing-library/react";
import { useDocumentPan } from "@/components/review/useDocumentPan";
import { ScrollRegion } from "@/components/ui";

function Preview({ enabled = true, sourceKey = "source:page:scale" }) {
  const { ref, handlers, dragging } = useDocumentPan(enabled, sourceKey);
  return (
    <ScrollRegion ref={ref} label="Document preview" {...handlers} data-dragging={dragging}>
      <div>
        <div data-testid="paper">Blank paper</div>
        <div className="textLayer">
          <span>Selectable PDF text</span>
        </div>
        <button type="button">word Evidence</button>
        <a href="#evidence">Evidence link</a>
      </div>
    </ScrollRegion>
  );
}

const release = vi.fn();
const capture = vi.fn();
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(400);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(300);
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(1100);
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(1400);
  HTMLElement.prototype.setPointerCapture = capture;
  HTMLElement.prototype.releasePointerCapture = release;
  HTMLElement.prototype.hasPointerCapture = () => true;
  capture.mockClear();
  release.mockClear();
});
afterEach(() => vi.restoreAllMocks());

// jsdom has no PointerEvent; retain real bubbling/cancellation semantics.
function pointer(target: Element, type: string, overrides: Record<string, unknown> = {}) {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: 200, clientY: 150, buttons: 1 });
  Object.defineProperties(
    event,
    Object.fromEntries(
      Object.entries({ pointerId: 1, pointerType: "mouse", ...overrides }).map(([key, value]) => [key, { value }]),
    ),
  );
  fireEvent(target, event);
  return event;
}

it("drags overflowing blank paper on both axes without changing the source", () => {
  render(<Preview />);
  const region = screen.getByRole("region", { name: "Document preview" });
  region.scrollLeft = 10;
  region.scrollTop = 20;
  expect(pointer(screen.getByTestId("paper"), "pointerdown").defaultPrevented).toBe(true);
  expect(capture).toHaveBeenCalledWith(1);
  pointer(region, "pointermove", { clientX: 120, clientY: 90 });
  expect([region.scrollLeft, region.scrollTop]).toEqual([90, 80]);
  expect(region).toHaveAttribute("data-dragging", "true");
  pointer(region, "pointerup");
  expect(release).toHaveBeenCalledWith(1);
  expect(region).toHaveAttribute("data-dragging", "false");
  pointer(region, "pointermove", { clientX: 20, clientY: 10 });
  expect([region.scrollLeft, region.scrollTop]).toEqual([90, 80]);
  expect(screen.getByText("Selectable PDF text")).toBeInTheDocument();
  expect(region).toHaveAttribute("tabindex", "0");
});

it.each(["Selectable PDF text", "word Evidence", "Evidence link"])("preserves native interaction with %s", (text) => {
  render(<Preview />);
  expect(pointer(screen.getByText(text), "pointerdown").defaultPrevented).toBe(false);
  expect(capture).not.toHaveBeenCalled();
});

it.each([{ pointerType: "touch" }, { pointerType: "pen" }, { button: 2 }, { clientX: 405 }])(
  "does not intercept non-primary mouse input or the scrollbar: %o",
  (overrides) => {
    render(<Preview />);
    expect(pointer(screen.getByTestId("paper"), "pointerdown", overrides).defaultPrevented).toBe(false);
    expect(capture).not.toHaveBeenCalled();
  },
);

it.each(["pointercancel", "lostpointercapture"])("stops on %s", (event) => {
  render(<Preview />);
  const paper = screen.getByTestId("paper");
  pointer(paper, "pointerdown");
  pointer(paper, event);
  pointer(paper, "pointermove", { clientX: 100 });
  expect(screen.getByRole("region")).toHaveAttribute("data-dragging", "false");
  expect(screen.getByRole("region").scrollLeft).toBe(0);
});

it("ends capture when the source/page/zoom changes or the preview unmounts", () => {
  const view = render(<Preview />);
  pointer(screen.getByTestId("paper"), "pointerdown");
  view.rerender(<Preview sourceKey="different-page" />);
  expect(release).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("region")).toHaveAttribute("data-dragging", "false");
  pointer(screen.getByTestId("paper"), "pointerdown");
  view.unmount();
  expect(release).toHaveBeenCalledTimes(2);
});

it("does not pan sheets or content that fits inside the preview", () => {
  const view = render(<Preview enabled={false} />);
  pointer(screen.getByTestId("paper"), "pointerdown");
  expect(capture).not.toHaveBeenCalled();
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(400);
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(300);
  view.rerender(<Preview enabled />);
  pointer(screen.getByTestId("paper"), "pointerdown");
  expect(capture).not.toHaveBeenCalled();
});

it("does not recapture old ground-truth text on pan release, but preserves a later text gesture", () => {
  render(<Preview />);
  const captureText = vi.fn();
  document.addEventListener("mouseup", captureText);
  try {
    const paper = screen.getByTestId("paper");
    pointer(paper, "pointerdown");
    pointer(paper, "pointerup");
    fireEvent.mouseUp(paper);
    expect(captureText).not.toHaveBeenCalled();
    const text = screen.getByText("Selectable PDF text");
    pointer(text, "pointerdown");
    pointer(text, "pointerup");
    fireEvent.mouseUp(text);
    expect(captureText).toHaveBeenCalledTimes(1);
  } finally {
    document.removeEventListener("mouseup", captureText);
  }
});

it("ignores another pointer and stops if the mouse button or window focus is lost", () => {
  render(<Preview />);
  const paper = screen.getByTestId("paper");
  pointer(paper, "pointerdown");
  pointer(paper, "pointermove", { pointerId: 2, clientX: 100 });
  expect(screen.getByRole("region").scrollLeft).toBe(0);
  pointer(paper, "pointermove", { buttons: 0 });
  expect(screen.getByRole("region")).toHaveAttribute("data-dragging", "false");
  pointer(paper, "pointerdown");
  fireEvent.blur(window);
  expect(screen.getByRole("region")).toHaveAttribute("data-dragging", "false");
});
