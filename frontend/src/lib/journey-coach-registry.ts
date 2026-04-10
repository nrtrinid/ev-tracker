import { ONBOARDING_STEPS } from "@/lib/onboarding";
import type { OnboardingStepId, ScannerSurface } from "@/lib/types";

export type JourneyCoachRoute = "home" | "scanner" | "parlay" | "bets";
export type JourneyCoachActionCommand =
  | "start_tutorial"
  | "review_scanner_pick"
  | "finish_tutorial";

export interface JourneyCoachAction {
  label: string;
  href?: string;
  variant?: "default" | "outline" | "secondary" | "ghost";
  icon?: "arrow" | "check";
  hideOnClick?: boolean;
  completeStepOnClick?: boolean;
  command?: JourneyCoachActionCommand;
}

export interface JourneyCoachStep {
  label: string;
  complete: boolean;
  active: boolean;
}

export interface JourneyCoachCandidate {
  key: string;
  persistStep?: OnboardingStepId;
  dismissStep?: OnboardingStepId;
  eyebrow: string;
  title: string;
  body: string;
  actions?: JourneyCoachAction[];
  steps?: JourneyCoachStep[];
  detailTitle?: string;
  detailBody?: string;
}

export interface JourneyCoachScannerReviewCandidate {
  surface: ScannerSurface;
  createdAt: string;
  bet: {
    event: string;
    market: string;
    sportsbook: string;
  };
}

export interface JourneyCoachTutorialPracticeBet {
  event: string;
  market: string;
  sportsbook: string;
}

export interface JourneyCoachContext {
  route: JourneyCoachRoute;
  scannerSurface?: ScannerSurface;
  scannerDrawerOpen: boolean;
  tutorialMode: boolean;
  tutorialDismissed: boolean;
  scannerReviewCandidate: JourneyCoachScannerReviewCandidate | null;
  tutorialPracticeBet: JourneyCoachTutorialPracticeBet | null;
  tutorialHasSeededScan: boolean;
  cartLength: number;
  homeSteps: JourneyCoachStep[];
}

interface JourneyCoachCandidateDefinition {
  id: string;
  route: JourneyCoachRoute;
  when: (context: JourneyCoachContext) => boolean;
  build: (context: JourneyCoachContext) => JourneyCoachCandidate;
}

function getActiveScannerReviewCandidate(context: JourneyCoachContext): JourneyCoachScannerReviewCandidate | null {
  if (context.route !== "scanner") {
    return null;
  }
  if (!context.scannerReviewCandidate || !context.scannerSurface) {
    return null;
  }
  if (context.scannerReviewCandidate.surface !== context.scannerSurface) {
    return null;
  }
  return context.scannerReviewCandidate;
}

const JOURNEY_COACH_CANDIDATES: readonly JourneyCoachCandidateDefinition[] = [
  {
    id: "home-tutorial-review",
    route: "home",
    when: (context) => context.tutorialMode && context.tutorialPracticeBet !== null,
    build: (context) => ({
      key: "home-tutorial-review",
      persistStep: ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS,
      eyebrow: "Step 3 of 3",
      title: "Practice ticket saved. Continue when you are ready.",
      body: "No auto-redirect. Tap the highlighted Bets button in the nav to continue the final step there.",
      steps: [
        { label: "Start Tutorial", complete: true, active: false },
        { label: "Practice Log", complete: true, active: false },
        { label: "Review in Bets", complete: false, active: true },
      ],
      detailTitle: context.tutorialPracticeBet!.event,
      detailBody: `${context.tutorialPracticeBet!.market} / ${context.tutorialPracticeBet!.sportsbook}`,
      actions: [
        {
          label: "Keep Exploring Markets",
          variant: "outline",
          hideOnClick: true,
        },
      ],
    }),
  },
  {
    id: "bets-tutorial-review",
    route: "bets",
    when: (context) => context.tutorialMode && context.tutorialPracticeBet !== null,
    build: (context) => ({
      key: "bets-tutorial-review",
      persistStep: ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS,
      eyebrow: "Step 3 of 3",
      title: "Finish tutorial from Bets",
      body: "Review your local practice ticket below, then tap Finish Tutorial when you are ready.",
      steps: [
        { label: "Start Tutorial", complete: true, active: false },
        { label: "Practice Log", complete: true, active: false },
        { label: "Review in Bets", complete: false, active: true },
      ],
      detailTitle: context.tutorialPracticeBet!.event,
      detailBody: `${context.tutorialPracticeBet!.market} / ${context.tutorialPracticeBet!.sportsbook}`,
      actions: [
        {
          label: "Finish Tutorial",
          icon: "check",
          command: "finish_tutorial",
        },
        {
          label: "Keep Exploring Bets",
          variant: "outline",
          hideOnClick: true,
        },
      ],
    }),
  },
  {
    id: "home-tutorial-intro",
    route: "home",
    when: (context) => context.tutorialMode && context.scannerReviewCandidate === null,
    build: (context) => ({
      key: "home-tutorial-intro",
      persistStep: ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS,
      eyebrow: "Daily Drops Tutorial",
      title: context.tutorialHasSeededScan
        ? "Step 2: Open a practice log from a sample line"
        : "Step 1: Start the simulated Daily Drops tutorial",
      body: context.tutorialHasSeededScan
        ? "Use one sample line below. Normally you would place at the book first; for this walkthrough you can jump straight into Practice Log."
        : "This walkthrough runs on a populated sample board so new users can learn safely without touching live lines.",
      steps: [
        {
          label: "Start Tutorial",
          complete: context.tutorialHasSeededScan,
          active: !context.tutorialHasSeededScan,
        },
        {
          label: "Practice Log",
          complete: false,
          active: context.tutorialHasSeededScan,
        },
        {
          label: "Review in Bets",
          complete: false,
          active: false,
        },
      ],
      actions: context.tutorialHasSeededScan
        ? [
            {
              label: "Keep Exploring Markets",
              variant: "outline",
              hideOnClick: true,
            },
          ]
        : [
            {
              label: "Start Walkthrough",
              icon: "check",
              command: "start_tutorial",
            },
          ],
    }),
  },
  {
    id: "home-scanner-review",
    route: "home",
    when: (context) => context.scannerReviewCandidate !== null,
    build: (context) => ({
      key: `home-review-${context.scannerReviewCandidate!.createdAt}`,
      dismissStep: ONBOARDING_STEPS.HOME_SCANNER_REVIEW,
      eyebrow: "Step 3 of 3",
      title: "Finish the pick you just placed",
      body: "Your last Daily Drops pick is saved here. Review and log it now so it lands in Open Bets and stays easy to track.",
      steps: context.homeSteps,
      actions: [
        {
          label: "Review Saved Pick",
          command: "review_scanner_pick",
          icon: "check",
        },
        {
          label: "Not Now",
          variant: "outline",
          hideOnClick: true,
        },
      ],
      detailTitle: context.scannerReviewCandidate!.bet.event,
      detailBody: `${context.scannerReviewCandidate!.bet.market} / ${context.scannerReviewCandidate!.bet.sportsbook}`,
    }),
  },
  {
    id: "scanner-tutorial-return-home",
    route: "scanner",
    when: (context) => (
      context.tutorialMode &&
      context.scannerSurface === "straight_bets" &&
      context.tutorialPracticeBet !== null
    ),
    build: () => ({
      key: "scanner-tutorial-return-home",
      eyebrow: "Tutorial Complete",
      title: "Daily Drops tutorial now lives on Markets",
      body: "Your next step is on the Markets page. Open Daily Drops there to continue the guided workflow.",
    }),
  },
  {
    id: "scanner-tutorial-empty",
    route: "scanner",
    when: (context) => (
      context.tutorialMode &&
      context.scannerSurface === "straight_bets" &&
      !context.tutorialHasSeededScan
    ),
    build: () => ({
      key: "scanner-tutorial-empty",
      persistStep: ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS,
      eyebrow: "Daily Drops Tutorial",
      title: "Scanner tutorial is deprecated",
      body: "Use the Markets page to learn the current Daily Drops flow. The scanner tutorial has been retired.",
      steps: [
        { label: "Open Markets", complete: false, active: true },
        { label: "Place at Book", complete: false, active: false },
        { label: "Review & Log", complete: false, active: false },
      ],
      actions: [
        {
          label: "Not Now",
          variant: "outline",
          hideOnClick: true,
        },
      ],
    }),
  },
  {
    id: "scanner-tutorial-ready",
    route: "scanner",
    when: (context) => context.tutorialMode && context.scannerSurface === "straight_bets",
    build: () => ({
      key: "scanner-tutorial-ready",
      persistStep: ONBOARDING_STEPS.TUTORIAL_SCANNER_STRAIGHT_BETS,
      eyebrow: "Daily Drops Tutorial",
      title: "Continue this tutorial on Markets",
      body: "Daily Drops is now the default workflow. Use the Markets board to place, review, and log your first tracked pick.",
      steps: [
        { label: "Open Markets", complete: true, active: false },
        { label: "Place at Book", complete: false, active: true },
        { label: "Review & Log", complete: false, active: false },
      ],
      detailTitle: "Workflow reminder",
      detailBody: "Markets cards include direct place links and review logging without scanner simulation.",
      actions: [
        {
          label: "Not Now",
          variant: "outline",
          hideOnClick: true,
        },
      ],
    }),
  },
  {
    id: "scanner-review-prompt",
    route: "scanner",
    when: (context) => getActiveScannerReviewCandidate(context) !== null && !context.scannerDrawerOpen,
    build: (context) => {
      const scannerReviewCandidate = getActiveScannerReviewCandidate(context)!;
      return {
        key: `scanner-review-${scannerReviewCandidate.createdAt}`,
        dismissStep: ONBOARDING_STEPS.SCANNER_REVIEW_PROMPT,
        eyebrow: "Step 3 of 3",
        title: `Placed it at ${scannerReviewCandidate.bet.sportsbook}? Review and log it.`,
        body: "We saved your last scanner pick so you can come back and confirm the bet in a few taps.",
        detailTitle: scannerReviewCandidate.bet.event,
        detailBody: `${scannerReviewCandidate.bet.market} / ${scannerReviewCandidate.bet.sportsbook}`,
        actions: [
          {
            label: "Review & Log Bet",
            command: "review_scanner_pick",
            icon: "check",
          },
          {
            label: "Keep Scanning",
            variant: "outline",
            hideOnClick: true,
          },
        ],
      };
    },
  },
  {
    id: "parlay-builder",
    route: "parlay",
    when: (context) => !context.tutorialDismissed && context.cartLength === 0,
    build: () => ({
      key: ONBOARDING_STEPS.PARLAY_BUILDER,
      persistStep: ONBOARDING_STEPS.PARLAY_BUILDER,
      eyebrow: "Optional Step",
      title: "Build parlays after you find Daily Drops plays",
      body: "The simplest beginner path is still one ticket at a time. When you want a multi-leg preview, add a couple of legs from Markets first by clicking the + button.",
      actions: [
        {
          label: "Find Legs in Markets",
          href: "/",
          icon: "arrow",
          completeStepOnClick: true,
        },
      ],
    }),
  },
  {
    id: "parlay-one-leg",
    route: "parlay",
    when: (context) => !context.tutorialDismissed && context.cartLength === 1,
    build: () => ({
      key: "parlay-one-leg",
      dismissStep: ONBOARDING_STEPS.PARLAY_ONE_LEG_PROMPT,
      eyebrow: "Optional Step",
      title: "Add one more leg to complete the preview",
      body: "You have one leg saved so far. Grab one more from Markets, then come back here to compare the combined payout.",
      actions: [
        {
          label: "Add Another Leg",
          href: "/",
          icon: "arrow",
        },
        {
          label: "Not Now",
          variant: "outline",
          hideOnClick: true,
        },
      ],
    }),
  },
];

export function selectJourneyCoachCandidate(context: JourneyCoachContext): JourneyCoachCandidate | null {
  for (const candidate of JOURNEY_COACH_CANDIDATES) {
    if (candidate.route !== context.route) {
      continue;
    }
    if (!candidate.when(context)) {
      continue;
    }
    return candidate.build(context);
  }
  return null;
}
