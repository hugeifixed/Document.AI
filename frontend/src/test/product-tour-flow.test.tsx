import { act, fireEvent, render, screen } from "@testing-library/react";
import { type ReactNode, StrictMode } from "react";

const tourControl = vi.hoisted(() => ({
  start: vi.fn(),
  tours: [] as Array<{ tour: string; steps: Array<{ title: string; blockKeyboardControl?: boolean }> }>,
}));

vi.mock("motion/react", () => ({ MotionConfig: ({ children }: { children: ReactNode }) => children }));
vi.mock("nextstepjs/adapters/react-router", () => ({
  useReactRouterAdapter: () => ({ push: () => {}, getCurrentPath: () => "/" }),
}));
vi.mock("nextstepjs", () => ({
  NextStepProvider: ({ children }: { children: ReactNode }) => children,
  useNextStep: () => ({ startNextStep: tourControl.start }),
  NextStepReact: ({
    children,
    onSkip,
    steps,
  }: {
    children: ReactNode;
    onSkip?: (step: number, tour: string) => void;
    steps: Array<{ tour: string; steps: Array<{ title: string; blockKeyboardControl?: boolean }> }>;
  }) => {
    tourControl.tours = steps;
    return (
      <>
        {children}
        <button type="button" onClick={() => onSkip?.(0, "platform-overview-mobile")}>
          Simulate dismiss
        </button>
      </>
    );
  },
}));

import { ProductTour } from "@/components/ProductTour";
import { hasAcknowledgedProductTour } from "@/components/productTourStorage";

async function nextFrame() {
  await act(async () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
}

describe("ProductTour first-run flow", () => {
  beforeEach(() => {
    localStorage.clear();
    tourControl.start.mockClear();
  });

  it("starts once in Strict Mode, remembers dismissal, and starts again when manually mounted", async () => {
    const finished = vi.fn();
    const view = render(
      <StrictMode>
        <ProductTour
          username="new.user"
          roles={["docai_operators", "docai_reviewers"]}
          onFinished={finished}
          onMobileNavigationChange={() => {}}
        />
      </StrictMode>,
    );
    await nextFrame();
    expect(tourControl.start).toHaveBeenCalledOnce();
    expect(tourControl.start).toHaveBeenCalledWith("platform-overview-mobile");
    expect(
      tourControl.tours.find(({ tour }) => tour === "platform-overview-desktop")?.steps.map(({ title }) => title),
    ).toEqual([
      "Set your working context",
      "Prepare documents and workflows",
      "Process and inspect",
      "Resolve human review",
      "Measure and share",
    ]);
    expect(
      tourControl.tours
        .find(({ tour }) => tour === "platform-overview-desktop")
        ?.steps.every(({ blockKeyboardControl }) => blockKeyboardControl),
    ).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Simulate dismiss" }));
    expect(hasAcknowledgedProductTour("new.user")).toBe(true);
    expect(finished).toHaveBeenCalledOnce();

    view.unmount();
    tourControl.start.mockClear();
    render(
      <ProductTour
        username="new.user"
        roles={[]}
        kind="detailed"
        onFinished={() => {}}
        onMobileNavigationChange={() => {}}
      />,
    );
    await nextFrame();
    expect(tourControl.start).toHaveBeenCalledOnce();
    expect(tourControl.start).toHaveBeenCalledWith("platform-detailed-mobile");
    const basicTitles = tourControl.tours
      .find(({ tour }) => tour === "platform-detailed-desktop")
      ?.steps.map(({ title }) => title);
    expect(basicTitles).not.toContain("New workflow version");
    expect(basicTitles).not.toContain("Review queue");
    expect(basicTitles).not.toContain("Ground truth");
  });
});
