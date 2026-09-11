import {
  AdjustmentsHorizontalIcon,
  Bars3Icon,
  CircleStackIcon,
  MoonIcon,
  UserCircleIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";
import { MotionConfig } from "motion/react";
import {
  NextStepProvider,
  NextStepReact,
  type CardComponentProps,
  type Tour,
  useNextStep,
} from "nextstepjs";
import { useReactRouterAdapter } from "nextstepjs/adapters/react-router";
import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";

const TOUR_VERSION = "1";
const DESKTOP_TOUR = "platform-overview-desktop";
const MOBILE_TOUR = "platform-overview-mobile";
const DESKTOP_QUERY = "(min-width: 64rem)"; // sidebar breakpoint (DESIGN.md §8.1): tablets portrait use the drawer
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
const CARD_REVEAL_DELAY_MS = 280;
const TourTransitionContext = createContext(false);

const commonEndSteps = [
  {
    icon: <MoonIcon className="size-5" aria-hidden="true" />,
    title: "Choose your appearance",
    content: "Switch between light and dark here. The full System setting remains available in Settings.",
    selector: "#tour-theme-toggle",
    side: "bottom-right" as const,
    pointerPadding: 10,
    pointerRadius: 8,
    disableInteraction: true,
  },
  {
    icon: <UserCircleIcon className="size-5" aria-hidden="true" />,
    title: "Your account and help",
    content: "Open this menu for settings, documentation, staff admin, logout, or to take this tour again.",
    selector: "#tour-account-menu",
    side: "bottom-right" as const,
    pointerPadding: 10,
    pointerRadius: 8,
    disableInteraction: true,
  },
];

const welcomeStep = {
  icon: <CircleStackIcon className="size-5" aria-hidden="true" />,
  title: "Welcome to DocAI",
  content: "This quick tour shows how to set context, follow document work, and find account tools.",
  side: "bottom" as const,
  pointerRadius: 10,
};

const tours: Tour[] = [
  {
    tour: DESKTOP_TOUR,
    steps: [
      welcomeStep,
      {
        icon: <AdjustmentsHorizontalIcon className="size-5" aria-hidden="true" />,
        title: "Set your working context",
        content: "Choose a project and dataset first. Pages and counts then stay scoped to the work you selected.",
        selector: "#tour-working-context",
        side: "right",
        pointerPadding: 12,
        pointerRadius: 8,
        disableInteraction: true,
      },
      {
        icon: <Bars3Icon className="size-5" aria-hidden="true" />,
        title: "Follow the document lifecycle",
        content: "Navigation moves from setup and processing through human review, evaluation, and export.",
        selector: "#tour-primary-navigation",
        side: "right",
        pointerPadding: 8,
        pointerRadius: 8,
        disableInteraction: true,
      },
      ...commonEndSteps,
    ],
  },
  {
    tour: MOBILE_TOUR,
    steps: [
      welcomeStep,
      {
        icon: <Bars3Icon className="size-5" aria-hidden="true" />,
        title: "Open your workspace",
        content: "Use this button to choose the active project and dataset, then move through each stage of document work.",
        selector: "#tour-navigation-trigger",
        side: "bottom-left",
        pointerPadding: 10,
        pointerRadius: 8,
        disableInteraction: true,
      },
      ...commonEndSteps,
    ],
  },
];

export function productTourStorageKey(username: string) {
  return `docai-product-tour:${TOUR_VERSION}:${encodeURIComponent(username)}`;
}

export function hasAcknowledgedProductTour(username: string) {
  try { return localStorage.getItem(productTourStorageKey(username)) === "acknowledged"; }
  catch { return false; }
}

export function acknowledgeProductTour(username: string) {
  try { localStorage.setItem(productTourStorageKey(username), "acknowledged"); }
  catch { /* Storage can be unavailable; the tour still remains usable. */ }
}

function currentTourName() {
  return window.matchMedia(DESKTOP_QUERY).matches ? DESKTOP_TOUR : MOBILE_TOUR;
}

function ProductTourCard({ step, currentStep, totalSteps, nextStep, prevStep, skipTour, arrow }: CardComponentProps) {
  const card = useRef<HTMLDialogElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const transitioning = useContext(TourTransitionContext);
  const titleId = useId();
  const contentId = useId();
  const lastStep = currentStep === totalSteps - 1;

  useEffect(() => {
    previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => previousFocus.current?.focus();
  }, []);

  useEffect(() => {
    const frame = requestAnimationFrame(() => card.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [currentStep]);

  function trapFocus(event: React.KeyboardEvent<HTMLDialogElement>) {
    if (event.key !== "Tab" || !card.current) return;
    const controls = [...card.current.querySelectorAll<HTMLElement>("button:not(:disabled), [href], [tabindex]:not([tabindex='-1'])")];
    if (controls.length === 0) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === card.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === card.current)) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <dialog
      open
      ref={card}
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={contentId}
      aria-busy={transitioning || undefined}
      tabIndex={-1}
      onKeyDown={trapFocus}
      className={`card elevation-modal m-0 w-56 max-w-[calc(100vw-2rem)] border border-base-300 bg-base-100 p-0 text-base-content focus:outline-none motion-safe:transition-opacity motion-safe:duration-[var(--motion-fast)] motion-safe:ease-in-out min-[24rem]:w-64 sm:w-80 ${transitioning ? "opacity-0" : "opacity-100"}`}
    >
      {arrow}
      <div className="card-body gap-3 p-4 sm:p-5">
        <div className="flex items-center gap-3">
          {step.icon && <span className="grid size-9 shrink-0 place-items-center rounded-field bg-base-200 text-primary" aria-hidden="true">{step.icon}</span>}
          <p className="min-w-0 flex-1 text-caption font-semibold uppercase tracking-wide text-secondary">Product tour</p>
          <button type="button" className="btn btn-square btn-ghost btn-sm shrink-0" onClick={skipTour} aria-label="Dismiss tour" title="Dismiss tour">
            <XMarkIcon className="size-5" aria-hidden="true" />
          </button>
        </div>
        <h2 id={titleId} className="text-section-title">{step.title}</h2>
        <p id={contentId} className="reading-copy text-sm text-secondary">{step.content}</p>
        <progress className="progress progress-primary h-1.5 w-full" value={currentStep + 1} max={totalSteps} aria-label={`Tour progress: step ${currentStep + 1} of ${totalSteps}`} />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-caption tabular-nums text-secondary">Step {currentStep + 1} of {totalSteps}</span>
          <div className="flex items-center gap-2">
            {currentStep > 0 && <button type="button" className="btn btn-ghost btn-sm" onClick={prevStep}>Back</button>}
            <button type="button" className="btn btn-primary btn-sm" onClick={nextStep}>{lastStep ? "Finish" : "Next"}</button>
          </div>
        </div>
      </div>
    </dialog>
  );
}

function ProductTourExperience({ username, children }: { username: string; children: (startTour: () => void) => ReactNode }) {
  const { startNextStep } = useNextStep();
  const autoStartedFor = useRef<string | null>(null);
  const revealTimer = useRef<number | undefined>(undefined);
  const [transitioning, setTransitioning] = useState(false);
  const startTour = useCallback(() => startNextStep(currentTourName()), [startNextStep]);
  const acknowledge = useCallback(() => acknowledgeProductTour(username), [username]);

  const beginStepTransition = useCallback(() => {
    if (window.matchMedia(REDUCED_MOTION_QUERY).matches) return;
    window.clearTimeout(revealTimer.current);
    setTransitioning(true);
    revealTimer.current = window.setTimeout(() => setTransitioning(false), CARD_REVEAL_DELAY_MS);
  }, []);

  useEffect(() => {
    if (!username || autoStartedFor.current === username || hasAcknowledgedProductTour(username)) return;
    const frame = requestAnimationFrame(() => {
      autoStartedFor.current = username;
      startTour();
    });
    return () => cancelAnimationFrame(frame);
  }, [startTour, username]);

  useEffect(() => () => window.clearTimeout(revealTimer.current), []);

  return (
    <MotionConfig reducedMotion="user">
      <TourTransitionContext.Provider value={transitioning}>
        <NextStepReact
          steps={tours}
          navigationAdapter={useReactRouterAdapter}
          cardComponent={ProductTourCard}
          cardTransition={{ duration: 0.4, ease: "easeInOut" }}
          arrowStyle={{ color: "var(--color-base-100)" }}
          shadowOpacity="0.52"
          onStepChange={beginStepTransition}
          onComplete={acknowledge}
          onSkip={acknowledge}
          disableConsoleLogs
          scrollToTop={false}
        >
          {children(startTour)}
        </NextStepReact>
      </TourTransitionContext.Provider>
    </MotionConfig>
  );
}

export function ProductTour({ username, children }: { username: string; children: (startTour: () => void) => ReactNode }) {
  return <NextStepProvider><ProductTourExperience username={username}>{children}</ProductTourExperience></NextStepProvider>;
}
