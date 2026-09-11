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
  type CardComponentProps,
  NextStepProvider,
  NextStepReact,
  type Tour,
  useNextStep,
} from "nextstepjs";
import { useReactRouterAdapter } from "nextstepjs/adapters/react-router";
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { acknowledgeProductTour } from "@/components/productTourStorage";
import { navigationTourTarget, visibleNavigationItems } from "@/navigation";

const DESKTOP_TOUR = "platform-overview-desktop";
const MOBILE_TOUR = "platform-overview-mobile";
const DESKTOP_QUERY = "(min-width: 64rem)"; // sidebar breakpoint (DESIGN.md §8.1): tablets portrait use the drawer
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
const CARD_FADE_MS = 120;
const TARGET_MOVE_MS = 160;
const DESKTOP_NAVIGATION_PREFIX = "tour-nav";
const MOBILE_NAVIGATION_PREFIX = "tour-mobile-nav";
const MOBILE_NAVIGATION_VIEWPORT = "tour-navigation-dialog";
const MOBILE_DRAWER_FIRST_STEP = 2;
type TourTransition = {
  transitioning: boolean;
  transitionTo: (action: () => void) => void;
};
const TourTransitionContext = createContext<TourTransition>({
  transitioning: false,
  transitionTo: (action) => action(),
});

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
    blockKeyboardControl: true,
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
    blockKeyboardControl: true,
  },
];

const welcomeStep = {
  icon: <CircleStackIcon className="size-5" aria-hidden="true" />,
  title: "Welcome to DocAI",
  content: "See how to set your working context and what happens in every stage of the document workflow.",
  side: "bottom" as const,
  pointerRadius: 10,
  blockKeyboardControl: true,
};

function navigationSteps(roles: string[], prefix: string, mobile = false) {
  return visibleNavigationItems(roles).map((item) => {
    const Icon = item.icon;
    return {
      icon: <Icon className="size-5" aria-hidden="true" />,
      title: item.label,
      content: item.tourDescription,
      selector: `#${navigationTourTarget(prefix, item)}`,
      side: "right" as const,
      pointerPadding: 8,
      pointerRadius: 8,
      disableInteraction: true,
      blockKeyboardControl: true,
      ...(mobile ? { viewportID: MOBILE_NAVIGATION_VIEWPORT } : {}),
    };
  });
}

function createTours(roles: string[]) {
  const desktopNavigationSteps = navigationSteps(roles, DESKTOP_NAVIGATION_PREFIX);
  const mobileNavigationSteps = navigationSteps(roles, MOBILE_NAVIGATION_PREFIX, true);
  const tours: Tour[] = [
    {
      tour: DESKTOP_TOUR,
      steps: [
        welcomeStep,
        {
          icon: <AdjustmentsHorizontalIcon className="size-5" aria-hidden="true" />,
          title: "Set your working context",
          content: "Choose a project and dataset first. Pages, counts, uploads, runs, and results then stay scoped to that work.",
          selector: "#tour-working-context",
          side: "right",
          pointerPadding: 12,
          pointerRadius: 8,
          disableInteraction: true,
          blockKeyboardControl: true,
        },
        ...desktopNavigationSteps,
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
          content: "This button opens the working context and the complete document workflow on smaller screens.",
          selector: "#tour-navigation-trigger",
          side: "bottom-left",
          pointerPadding: 10,
          pointerRadius: 8,
          disableInteraction: true,
          blockKeyboardControl: true,
        },
        {
          icon: <AdjustmentsHorizontalIcon className="size-5" aria-hidden="true" />,
          title: "Set your working context",
          content: "Choose a project and dataset first. Pages, counts, uploads, runs, and results then stay scoped to that work.",
          selector: "#tour-mobile-working-context",
          side: "right",
          pointerPadding: 12,
          pointerRadius: 8,
          disableInteraction: true,
          blockKeyboardControl: true,
          viewportID: MOBILE_NAVIGATION_VIEWPORT,
        },
        ...mobileNavigationSteps,
        ...commonEndSteps,
      ],
    },
  ];

  return {
    tours,
    mobileDrawerLastStep: MOBILE_DRAWER_FIRST_STEP + mobileNavigationSteps.length,
  };
}

function currentTourName() {
  return window.matchMedia(DESKTOP_QUERY).matches ? DESKTOP_TOUR : MOBILE_TOUR;
}

function ProductTourCard({ step, currentStep, totalSteps, nextStep, prevStep, skipTour, arrow }: CardComponentProps) {
  const card = useRef<HTMLDialogElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const { transitioning, transitionTo } = useContext(TourTransitionContext);
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

  function handleKeyDown(event: React.KeyboardEvent<HTMLDialogElement>) {
    trapFocus(event);
    if (transitioning) return;

    let action: (() => void) | undefined;
    if (event.key === "ArrowRight") action = nextStep;
    if (event.key === "ArrowLeft" && currentStep > 0) action = prevStep;
    if (event.key === "Escape") action = () => skipTour?.();
    if (!action) return;

    event.preventDefault();
    event.stopPropagation();
    transitionTo(action);
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
      onKeyDown={handleKeyDown}
      className={`card elevation-modal m-0 w-56 max-w-[calc(100vw-2rem)] border border-base-300 bg-base-100 p-0 text-base-content focus:outline-none motion-safe:transition-opacity motion-safe:duration-[var(--motion-fast)] motion-safe:ease-in-out min-[24rem]:w-64 sm:w-80 ${transitioning ? "opacity-0" : "opacity-100"}`}
    >
      {arrow}
      <div className="card-body gap-3 p-4 sm:p-5">
        <div className="flex items-center gap-3">
          {step.icon && <span className="grid size-9 shrink-0 place-items-center rounded-field bg-base-200 text-primary" aria-hidden="true">{step.icon}</span>}
          <p className="min-w-0 flex-1 text-caption font-semibold uppercase tracking-wide text-secondary">Product tour</p>
          <button type="button" className="btn btn-square btn-ghost btn-sm shrink-0" disabled={transitioning} onClick={() => transitionTo(() => skipTour?.())} aria-label="Dismiss tour" title="Dismiss tour">
            <XMarkIcon className="size-5" aria-hidden="true" />
          </button>
        </div>
        <h2 id={titleId} className="text-section-title">{step.title}</h2>
        <p id={contentId} className="reading-copy text-sm text-secondary">{step.content}</p>
        <progress className="progress progress-primary h-1.5 w-full" value={currentStep + 1} max={totalSteps} aria-label={`Tour progress: step ${currentStep + 1} of ${totalSteps}`} />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-caption tabular-nums text-secondary">Step {currentStep + 1} of {totalSteps}</span>
          <div className="flex items-center gap-2">
            {currentStep > 0 && <button type="button" className="btn btn-ghost btn-sm" disabled={transitioning} onClick={() => transitionTo(prevStep)}>Back</button>}
            <button type="button" className="btn btn-primary btn-sm" disabled={transitioning} onClick={() => transitionTo(nextStep)}>{lastStep ? "Finish" : "Next"}</button>
          </div>
        </div>
      </div>
    </dialog>
  );
}

type ProductTourProps = {
  username: string;
  roles: string[];
  onFinished: () => void;
  onMobileNavigationChange: (open: boolean) => void;
};

function ProductTourExperience({ username, roles, onFinished, onMobileNavigationChange }: ProductTourProps) {
  const { startNextStep } = useNextStep();
  const autoStartedFor = useRef<string | null>(null);
  const transitionTimers = useRef<number[]>([]);
  const [transitioning, setTransitioning] = useState(false);
  const tourConfiguration = useMemo(() => createTours(roles), [roles]);
  const startTour = useCallback(() => {
    onMobileNavigationChange(false);
    startNextStep(currentTourName());
  }, [onMobileNavigationChange, startNextStep]);
  const acknowledge = useCallback(() => {
    onMobileNavigationChange(false);
    acknowledgeProductTour(username);
    onFinished();
  }, [onFinished, onMobileNavigationChange, username]);

  const clearTransitionTimers = useCallback(() => {
    transitionTimers.current.forEach((timer) => window.clearTimeout(timer));
    transitionTimers.current = [];
  }, []);

  const transitionTo = useCallback((action: () => void) => {
    clearTransitionTimers();
    if (window.matchMedia(REDUCED_MOTION_QUERY).matches) {
      action();
      return;
    }

    setTransitioning(true);
    const exitTimer = window.setTimeout(() => {
      action();
      const revealTimer = window.setTimeout(() => {
        setTransitioning(false);
        transitionTimers.current = [];
      }, TARGET_MOVE_MS);
      transitionTimers.current = [revealTimer];
    }, CARD_FADE_MS);
    transitionTimers.current = [exitTimer];
  }, [clearTransitionTimers]);

  const changeStep = useCallback((nextStep: number, tourName: string | null) => {
    if (tourName !== MOBILE_TOUR) return;
    onMobileNavigationChange(
      nextStep >= MOBILE_DRAWER_FIRST_STEP && nextStep <= tourConfiguration.mobileDrawerLastStep,
    );
  }, [onMobileNavigationChange, tourConfiguration.mobileDrawerLastStep]);

  useEffect(() => {
    if (!username || autoStartedFor.current === username) return;
    const frame = requestAnimationFrame(() => {
      autoStartedFor.current = username;
      startTour();
    });
    return () => cancelAnimationFrame(frame);
  }, [startTour, username]);

  useEffect(() => () => {
    clearTransitionTimers();
    onMobileNavigationChange(false);
  }, [clearTransitionTimers, onMobileNavigationChange]);

  return (
    <MotionConfig reducedMotion="user">
      <TourTransitionContext.Provider value={{ transitioning, transitionTo }}>
        <NextStepReact
          steps={tourConfiguration.tours}
          navigationAdapter={useReactRouterAdapter}
          cardComponent={ProductTourCard}
          cardTransition={{ duration: TARGET_MOVE_MS / 1000, ease: "easeInOut" }}
          arrowStyle={{ color: "var(--color-base-100)" }}
          shadowOpacity="0.52"
          onStepChange={changeStep}
          onComplete={acknowledge}
          onSkip={acknowledge}
          disableConsoleLogs
          scrollToTop={false}
        >
          {null}
        </NextStepReact>
      </TourTransitionContext.Provider>
    </MotionConfig>
  );
}

export function ProductTour(props: ProductTourProps) {
  return <NextStepProvider><ProductTourExperience {...props} /></NextStepProvider>;
}
