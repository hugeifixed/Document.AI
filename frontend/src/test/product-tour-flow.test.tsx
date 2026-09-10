import { act, fireEvent, render, screen } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";

const tourControl = vi.hoisted(() => ({ start: vi.fn() }));

vi.mock("motion/react", () => ({ MotionConfig: ({ children }: { children: ReactNode }) => children }));
vi.mock("nextstepjs/adapters/react-router", () => ({ useReactRouterAdapter: () => ({ push: () => {}, getCurrentPath: () => "/" }) }));
vi.mock("nextstepjs", () => ({
  NextStepProvider: ({ children }: { children: ReactNode }) => children,
  useNextStep: () => ({ startNextStep: tourControl.start }),
  NextStepReact: ({ children, onSkip }: { children: ReactNode; onSkip?: (step: number, tour: string) => void }) => (
    <>{children}<button type="button" onClick={() => onSkip?.(0, "platform-overview-mobile")}>Simulate dismiss</button></>
  ),
}));

import { ProductTour, hasAcknowledgedProductTour } from "@/components/ProductTour";

async function nextFrame() {
  await act(async () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
}

describe("ProductTour first-run flow", () => {
  beforeEach(() => {
    localStorage.clear();
    tourControl.start.mockClear();
  });

  it("starts once in Strict Mode, remembers dismissal, and still allows manual replay", async () => {
    const view = render(
      <StrictMode>
        <ProductTour username="new.user">{(startTour) => <button type="button" onClick={startTour}>Take a tour</button>}</ProductTour>
      </StrictMode>,
    );
    await nextFrame();
    expect(tourControl.start).toHaveBeenCalledOnce();
    expect(tourControl.start).toHaveBeenCalledWith("platform-overview-mobile");

    fireEvent.click(screen.getByRole("button", { name: "Simulate dismiss" }));
    expect(hasAcknowledgedProductTour("new.user")).toBe(true);

    view.unmount();
    tourControl.start.mockClear();
    render(<ProductTour username="new.user">{(startTour) => <button type="button" onClick={startTour}>Take a tour</button>}</ProductTour>);
    await nextFrame();
    expect(tourControl.start).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Take a tour" }));
    expect(tourControl.start).toHaveBeenCalledOnce();
  });
});
