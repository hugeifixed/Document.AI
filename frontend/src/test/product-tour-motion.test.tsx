import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentType, ReactNode } from "react";

interface MockCardProps {
  step: { title: string; content: ReactNode; icon: null };
  currentStep: number;
  totalSteps: number;
  nextStep: () => void;
  prevStep: () => void;
  skipTour: () => void;
  arrow: ReactNode;
}

const tourControl = vi.hoisted(() => ({
  start: vi.fn(),
  transition: undefined as { duration?: number; ease?: string } | undefined,
}));

vi.mock("motion/react", () => ({ MotionConfig: ({ children }: { children: ReactNode }) => children }));
vi.mock("nextstepjs/adapters/react-router", () => ({ useReactRouterAdapter: () => ({ push: () => {}, getCurrentPath: () => "/" }) }));
vi.mock("nextstepjs", () => ({
  NextStepProvider: ({ children }: { children: ReactNode }) => children,
  useNextStep: () => ({ startNextStep: tourControl.start }),
  NextStepReact: ({ children, cardComponent: Card, cardTransition, onStepChange }: {
    children: ReactNode;
    cardComponent: ComponentType<MockCardProps>;
    cardTransition: { duration?: number; ease?: string };
    onStepChange?: (step: number, tour: string) => void;
  }) => {
    tourControl.transition = cardTransition;
    return <>
      {children}
      <Card
        step={{ title: "Follow the document lifecycle", content: "Tour content", icon: null }}
        currentStep={2}
        totalSteps={5}
        nextStep={() => onStepChange?.(3, "platform-overview-desktop")}
        prevStep={() => {}}
        skipTour={() => {}}
        arrow={<span />}
      />
    </>;
  },
}));

import { ProductTour } from "@/components/ProductTour";

describe("ProductTour motion", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("synchronizes the card with the spotlight and fades through large target changes", () => {
    vi.useFakeTimers();
    render(<ProductTour username="motion.user">{() => <main>Application</main>}</ProductTour>);

    expect(tourControl.transition).toEqual({ duration: 0.4, ease: "easeInOut" });
    const card = screen.getByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(card).toHaveClass("opacity-0");
    expect(card).toHaveAttribute("aria-busy", "true");

    act(() => vi.advanceTimersByTime(280));
    expect(card).toHaveClass("opacity-100");
    expect(card).not.toHaveAttribute("aria-busy");
  });

  it("changes steps immediately when reduced motion is requested", () => {
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    render(<ProductTour username="reduced-motion.user">{() => <main>Application</main>}</ProductTour>);

    const card = screen.getByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(card).toHaveClass("opacity-100");
    expect(card).not.toHaveAttribute("aria-busy");
  });
});
