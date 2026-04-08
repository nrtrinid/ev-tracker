"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  ONBOARDING_HIGHLIGHT_TARGETS,
  ONBOARDING_HIGHLIGHT_MESSAGES,
  type OnboardingHighlightMessage,
  type OnboardingHighlightTarget,
} from "@/lib/onboarding-guidance";

interface OnboardingHighlightState {
  target: OnboardingHighlightTarget | null;
  message: OnboardingHighlightMessage | null;
}

interface OnboardingHighlightContextValue {
  activeTarget: OnboardingHighlightTarget | null;
  highlight: (target: OnboardingHighlightTarget, message?: OnboardingHighlightMessage) => void;
  clear: () => void;
}

const OnboardingHighlightContext = createContext<OnboardingHighlightContextValue | null>(null);

const ACTIVE_TARGET_CLASS_NAMES = [
  "ring-2",
  "ring-primary",
  "ring-offset-2",
  "ring-offset-background",
  "animate-pulse",
];

const NON_MODAL_TARGETS = new Set<OnboardingHighlightTarget>([
  ONBOARDING_HIGHLIGHT_TARGETS.COACH_START_WALKTHROUGH,
]);

function rectChanged(previous: DOMRect | null, next: DOMRect): boolean {
  if (!previous) return true;
  const epsilon = 0.5;
  return (
    Math.abs(previous.top - next.top) > epsilon ||
    Math.abs(previous.left - next.left) > epsilon ||
    Math.abs(previous.width - next.width) > epsilon ||
    Math.abs(previous.height - next.height) > epsilon
  );
}

export function OnboardingHighlightProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<OnboardingHighlightState>({
    target: null,
    message: null,
  });
  const [spotlightRect, setSpotlightRect] = useState<DOMRect | null>(null);
  const activeElementRef = useRef<HTMLElement | null>(null);
  const scrolledTargetRef = useRef<OnboardingHighlightTarget | null>(null);

  const clearTargetClasses = useCallback(() => {
    const element = activeElementRef.current;
    if (!element) return;
    element.classList.remove(...ACTIVE_TARGET_CLASS_NAMES);
    element.removeAttribute("data-onboarding-active");
    activeElementRef.current = null;
  }, []);

  const clear = useCallback(() => {
    setState({ target: null, message: null });
    setSpotlightRect(null);
    scrolledTargetRef.current = null;
  }, []);

  const highlight = useCallback(
    (target: OnboardingHighlightTarget, message?: OnboardingHighlightMessage) => {
      setState({
        target,
        message: message ?? ONBOARDING_HIGHLIGHT_MESSAGES[target],
      });
    },
    []
  );

  useEffect(() => {
    clearTargetClasses();

    if (!state.target) {
      setSpotlightRect(null);
      return;
    }

    let isDisposed = false;
    let rafId = 0;
    let missingTargetTimeout: number | null = null;

    const updateTargetRect = () => {
      if (isDisposed) return;

      const element = document.querySelector<HTMLElement>(
        `[data-onboarding-target="${state.target}"]`
      );

      if (!element) {
        clearTargetClasses();
        setSpotlightRect((current) => (current ? null : current));
        if (!missingTargetTimeout) {
          missingTargetTimeout = window.setTimeout(() => {
            if (isDisposed) return;
            clear();
          }, 1500);
        }
        return;
      }

      if (missingTargetTimeout) {
        window.clearTimeout(missingTargetTimeout);
        missingTargetTimeout = null;
      }

      if (activeElementRef.current !== element) {
        clearTargetClasses();
        activeElementRef.current = element;
        element.classList.add(...ACTIVE_TARGET_CLASS_NAMES);
        element.setAttribute("data-onboarding-active", "true");
      }

      if (scrolledTargetRef.current !== state.target) {
        element.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
        scrolledTargetRef.current = state.target;
      }

      const nextRect = element.getBoundingClientRect();
      setSpotlightRect((current) => (rectChanged(current, nextRect) ? nextRect : current));
    };

    const scheduleUpdate = () => {
      if (isDisposed) return;
      if (rafId) {
        window.cancelAnimationFrame(rafId);
      }
      rafId = window.requestAnimationFrame(() => {
        rafId = 0;
        updateTargetRect();
      });
    };

    scheduleUpdate();

    const mutationObserver = new MutationObserver(scheduleUpdate);
    mutationObserver.observe(document.body, {
      childList: true,
      subtree: true,
    });

    const handleReflow = () => {
      scheduleUpdate();
    };

    const handleDocumentClick = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest(`[data-onboarding-target="${state.target}"]`)) {
        clear();
      }
    };

    window.addEventListener("resize", handleReflow);
    window.addEventListener("scroll", handleReflow, true);
    document.addEventListener("click", handleDocumentClick, true);

    return () => {
      isDisposed = true;
      if (rafId) {
        window.cancelAnimationFrame(rafId);
      }
      if (missingTargetTimeout) {
        window.clearTimeout(missingTargetTimeout);
      }
      mutationObserver.disconnect();
      window.removeEventListener("resize", handleReflow);
      window.removeEventListener("scroll", handleReflow, true);
      document.removeEventListener("click", handleDocumentClick, true);
      clearTargetClasses();
    };
  }, [clear, clearTargetClasses, state.target]);

  const spotlightStyle = useMemo(() => {
    if (!spotlightRect) return undefined;

    const inset = 8;
    return {
      top: Math.max(0, spotlightRect.top - inset),
      left: Math.max(0, spotlightRect.left - inset),
      width: spotlightRect.width + inset * 2,
      height: spotlightRect.height + inset * 2,
    };
  }, [spotlightRect]);

  const isNonModalTarget = useMemo(() => {
    if (!state.target) return false;
    return NON_MODAL_TARGETS.has(state.target);
  }, [state.target]);

  return (
    <OnboardingHighlightContext.Provider
      value={{
        activeTarget: state.target,
        highlight,
        clear,
      }}
    >
      {children}
      {state.target && spotlightStyle && (
        <div className="pointer-events-none fixed inset-0 z-[90]">
          {!isNonModalTarget && <div className="absolute inset-0 bg-black/45" />}
          <div
            className="absolute rounded-xl border border-primary/70 shadow-[0_0_0_9999px_rgba(0,0,0,0.45)] transition-all duration-200"
            style={
              isNonModalTarget
                ? {
                    ...spotlightStyle,
                    boxShadow: "0 10px 30px rgba(59,130,246,0.18)",
                  }
                : spotlightStyle
            }
          />
          {state.message && (
            <div className="absolute left-1/2 top-6 w-[min(34rem,calc(100%-2rem))] -translate-x-1/2 rounded-lg border border-primary/35 bg-card/95 px-3 py-2 text-sm shadow-lg backdrop-blur-sm">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">Guided Step</p>
              <p className="mt-1 font-medium text-foreground">{state.message.title}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{state.message.body}</p>
            </div>
          )}
        </div>
      )}
    </OnboardingHighlightContext.Provider>
  );
}

export function useOnboardingHighlight() {
  const context = useContext(OnboardingHighlightContext);
  if (!context) {
    throw new Error("useOnboardingHighlight must be used inside OnboardingHighlightProvider");
  }
  return context;
}
