# FUTURE_PLANS

Last updated: 2026-04-21
Source: Pass 2 roadmap revision (trusted beta hardening + recent beta analytics review)
Planning mode: trusted beta hardening before wider beta expansion

This file is a living roadmap, not an idea backlog. Items stay here only if they protect user trust/reliability, make beta signal more trustworthy, or are the next clear expansion step after the trust baseline is stable.

Status legend:
- `[ ]` not started
- `[-]` in progress
- `[x]` completed

## Current stage

- Trusted beta hardening.
- Core product paths are implemented and in active use: scanner, board, player props, deeplinks, parlay, onboarding/settings, and admin ops tooling.
- Primary risk is reliability drift, attribution gaps, and regression risk, not missing core feature breadth.
- Near-term priority is to tighten trust-critical behavior, coverage, and measurement before adding expansion work.

## Must ship before wider beta

Focus: trust/reliability fixes only.

- [ ] Apply duplicate-state tags consistently across all scanner cards (not only player props): `Already Placed`, `Placed Elsewhere`, and `Better Now`. [Owner: Backend/Frontend] [Target week: 2026-W17]
  - Why: Duplicate labels influence logging and exposure decisions; inconsistent card tagging breaks user trust quickly.
  - User impact: High.
  - Engineering risk: Medium.
  - Next step: Align annotation and rendering paths for straight bets + player props, then add integration/UI tests that assert all three states on both card types.
  - Codex fit: High.

- [x] Add dedicated middleware regression tests for auth + beta gating flows. [Owner: Frontend] [Completed: 2026-04-21]
  - Why: Middleware is the main access gate and redirect layer, but dedicated flow coverage is thin.
  - User impact: High.
  - Engineering risk: Low to medium.
  - Completed work: Added a dedicated middleware regression spec that exercises the trusted-beta redirect matrix for unauthenticated access, approved and non-approved beta users, admin allowlist bypass, auth-page redirects, and middleware bypass routes for cron, backend proxy, and beta-access APIs.
  - Codex fit: High.

- [x] Normalize supported alt-line parsing across active beta books/markets (for example, `O/U 1.5` vs ladder formats that begin at `+2`). [Owner: Backend] [Completed: 2026-04-21]
  - Why: Schema differences across books can cause the parser to miss edges or misalign comparable lines, degrading weighted-median trust.
  - User impact: High.
  - Engineering risk: High.
  - Completed work: Added canonical alternate-line normalization for MLB batter total bases so ladder offers like `2+` can price against the equivalent `over 1.5` threshold, while keeping one-sided ladder books as target offers and preserving paired-reference fair-odds math.
  - Follow-up: Extend the same normalization pattern to any remaining active beta book/market shapes that still diverge from the standard paired-line representation.
  - Codex fit: Extremely high.

- [ ] Canonicalize beta telemetry, attribution, and event dedupe. [Owner: Frontend/Backend] [Target week: 2026-W17]
  - Why: Current beta analytics can show dropped funnels (`tutorial_completed=Unknown`, `board_viewed=Unknown`), impossible conversion math, and likely duplicate firing on `bet_logged`. Without canonical event definitions, idempotency, and source attribution, beta product decisions are noisy.
  - User impact: Low direct, critical for product direction and operator trust.
  - Engineering risk: Low to medium.
  - Next step: Define a canonical event schema, add idempotency keys, flag internal/test accounts, and attach source metadata (`origin_surface`, `book`, `market`, `edge_bucket`, `opportunity_id` when available), then add invariants/tests for funnel math.
  - Codex fit: High.

- [ ] Expand board route contract coverage for latest modes, surface endpoint, and scoped refresh behavior. [Owner: Backend] [Target week: 2026-W18]
  - Why: Board routes are complex and central to first impression reliability.
  - User impact: High.
  - Engineering risk: Medium.
  - Next step: Add route-level tests for mode handling, rate-limit/error branches, and scoped refresh contracts.
  - Codex fit: High.

- [x] Ensure daily-board pipeline card reflects the latest ops manual refresh state (no stale board status after manual refresh). [Owner: Backend/Frontend] [Completed: 2026-04-21]
  - Why: Operators report cases where manual refresh succeeds but the board pipeline card still shows stale state.
  - User impact: High (trust in board freshness and operator confidence).
  - Engineering risk: Medium.
  - Completed work: Added normalized `last_board_refresh` ops status across board-drop and scoped-refresh paths, persisted scoped refreshes into durable ops history without republishing canonical `board:latest`, and updated the ops dashboard to poll short-term after async refresh acceptance so the cards settle without waiting for the next background refetch window.
  - Regression coverage: Added backend tests for scoped-refresh success/failure status persistence plus ops-history selection of the freshest board-affecting refresh, and updated scheduler/ops-trigger status assertions.
  - Follow-up: Keep the broader board route contract expansion item below open for more exhaustive mode/rate-limit/scoped-refresh route coverage.
  - Codex fit: High.

- [ ] Audit deeplink reliability and fallback behavior by sportsbook/platform. [Owner: Frontend/Product/Ops] [Target week: 2026-W18]
  - Why: Finding an edge is not enough if the handoff to the sportsbook is unreliable. App-vs-web, geo-plugin, and platform-specific friction can make a "working" deeplink practically unusable.
  - User impact: High.
  - Engineering risk: Medium.
  - Next step: Build a per-book matrix across desktop/mobile/app, verify expected fallback behavior, and add per-book UI hints or graceful fallback copy where direct reachability is weak.
  - Codex fit: Good for the matrix and fallback implementation; final QA needs human validation.

- [x] Re-add CLV piggyback on admin-triggered scans for currently placed bets with CLV pending (not only JIT scheduler job coverage). [Owner: Backend] [Completed: 2026-04-21]
  - Why: CLV pending bets can miss timely updates when only the JIT path runs; admin-triggered scans should also advance CLV snapshots.
  - User impact: Medium to high (faster CLV visibility on active bets).
  - Engineering risk: Medium.
  - Completed work: Admin-triggered board refresh now piggybacks `main._piggyback_clv` on successful board-drop runs using only fresh sides returned by `run_daily_board_drop` (`fresh_straight_sides` + `fresh_prop_sides`).
  - Regression coverage: Added backend ops-trigger contract coverage for sync/async piggyback wiring, empty fresh-side skip behavior, and best-effort failure isolation when piggyback execution raises.
  - Follow-up: Keep the existing JIT CLV scheduler path unchanged as the safety-net close-line refresher.
  - Codex fit: High.

- [ ] Resolve release/docs/runtime parity drift across status docs. [Owner: Docs] [Target week: 2026-W17]
  - Why: Inconsistent release metadata causes operator confusion and weakens launch discipline.
  - User impact: Medium (operator-facing, but impacts release confidence).
  - Engineering risk: Low.
  - Next step: Align README/runbook/handoff release baseline and add a lightweight parity checklist to release flow.
  - Codex fit: High.

## Should ship soon after

Focus: reliability polish and operational confidence after must-ship items land.

- [ ] Stabilize Journey Coach behavior and add direct component/regression coverage. [Owner: Frontend] [Target week: 2026-W18]
  - Why: Onboarding reliability affects early user confidence and retention.
  - User impact: Medium to high.
  - Engineering risk: Medium.
  - Next step: Lock persistence/hydration behavior and add focused tests for dismiss/complete/revisit flows.
  - Codex fit: Good for implementation and tests; final UX acceptance needs human review.

- [-] Stabilize beta analytics semantics and move drilldown into a dedicated ops analytics page. [Owner: Frontend/Backend/Ops] [Target week: 2026-W18]
  - Why: Current summary metrics can disagree or produce invalid conversion rates. Operators need a trustworthy read layer for beta follow-up without overloading the main ops homepage.
  - User impact: Low for external testers, medium for operator decision quality.
  - Engineering risk: Low to medium.
  - Progress update (2026-04-21): Updated ops research diagnostics `By market` count display to show `captured_count / valid_close_count`, so effective CLV sample size is explicit instead of implied by captured rows alone.
  - Next step: Keep a compact beta-health snapshot on the ops homepage, move the detailed drilldown to a dedicated subpage, and add denominator/invariant guards so invalid funnel math is surfaced clearly.
  - Codex fit: High.

- [ ] Automate the current manual opportunity curation logic. [Owner: Backend] [Target week: 2026-W18]
  - Why: Manual curation is still a human bottleneck. Translating the real-world checklist into code reduces weak/false opportunities and makes the board more usable for new testers.
  - User impact: High.
  - Engineering risk: Medium.
  - Next step: Convert the current mental checklist into programmatic filters/ranking rules inside the opportunity pipeline, then compare against recent manually accepted/rejected examples.
  - Codex fit: High.

- [ ] Resolve Pick'em view UI debt for California beta testers. [Owner: Frontend] [Target week: 2026-W18]
  - Why: Pick'em is the main usable lane for California testers. Fixing their reported UI issues keeps a real external beta cohort engaged and able to validate fantasy-style prop workflows.
  - User impact: High for the CA cohort.
  - Engineering risk: Low.
  - Next step: Triage the current Alex-reported issue list, batch the CSS/state fixes, and re-test against actual CA-compatible usage flows.
  - Codex fit: High.

- [ ] Add internal coverage diagnostics for partial or unsupported book/market combinations. [Owner: Backend/Ops] [Target week: 2026-W19]
  - Why: It is currently too easy to confuse true market absence, delayed population, one-sided ladder evidence, and parsing failure. Operators need to know which case they are looking at.
  - User impact: Medium.
  - Engineering risk: Medium.
  - Next step: Surface a small internal support matrix or reason code (`unsupported`, `not_yet_populated`, `one_sided_only`, `parse_failed`) for key book/market paths.
  - Codex fit: High.

- [ ] Add explicit frontend bridge tests for ops analytics summary/users routes. [Owner: Frontend] [Target week: 2026-W19]
  - Why: Internal analytics tooling exists but route-level bridge confidence can be stronger.
  - User impact: Low for external testers, medium for operator reliability.
  - Engineering risk: Low.
  - Next step: Add auth, timeout, and error-shape tests for these two bridge handlers.
  - Codex fit: High.

- [ ] Add scan cadence visibility first, then lightweight operator controls for book/market polling if still needed. [Owner: Backend/Ops] [Target week: 2026-W19]
  - Why: If freshness issues persist, operators need better visibility than deploy-edit-redeploy loops. Exposing cadence is lower risk than jumping directly to broad mutable controls.
  - User impact: Indirect, but helps preserve board freshness.
  - Engineering risk: Medium.
  - Next step: Expose current polling cadence and last successful scan timings in ops; only add mutable controls if manual tuning remains a repeated operational need.
  - Codex fit: High.

- [ ] Establish a recurring post-fix smoke run for launch-critical flows. [Owner: Ops] [Target week: 2026-W19]
  - Why: Static correctness is not enough near launch; runtime checks catch integration drift.
  - User impact: Medium to high.
  - Engineering risk: Low.
  - Next step: Run and document smoke checks for scanner, board, auth/beta gate, deeplinks, and ops health on each release candidate.
  - Codex fit: Partial. Good for checklist automation, but environment validation requires human review.

## Later / only after trust baseline is stable

Focus: feature expansion.

- [ ] Monetization and entitlement system (billing/subscription/paywall architecture). [Owner: Product/Backend] [Target week: backlog]
  - Why later: Not required for trusted beta stabilization, but required for broader commercial rollout.
  - User impact: Low now, high later.
  - Engineering risk: High.
  - Next step: Product + architecture decision first, then phased implementation.
  - Codex fit: Good after design lock; not for first-pass business policy decisions.

- [ ] Alt pitcher K lookup productization decision. [Owner: Product/Ops] [Target week: backlog]
  - Current status: Keep internal/admin for now.
  - Why later: Useful capability, but user-facing framing and confidence guardrails are not launch-critical.
  - User impact: Low to medium now.
  - Engineering risk: Medium.
  - Next step: Gather internal usage signal, then evaluate limited user rollout.
  - Codex fit: Partial.

- [ ] Ops analytics drilldown productization decision. [Owner: Product/Ops] [Target week: backlog]
  - Current status: Keep internal/admin for now.
  - Why later: Internal follow-up tooling is valuable, but user-facing exposure needs clear product intent and privacy framing.
  - User impact: Low now.
  - Engineering risk: Medium.
  - Next step: Define explicit user-facing outcomes before exposing any portion externally.
  - Codex fit: Partial.

- [ ] User-facing controls for degraded board/system modes. [Owner: Product/Backend] [Target week: backlog]
  - Current status: Keep internal/operator-oriented for now.
  - Why later: Adds complexity with limited immediate ROI during trusted beta hardening.
  - User impact: Low now.
  - Engineering risk: Medium.
  - Next step: Revisit after reliability baseline is consistently met.
  - Codex fit: Good later.

## Ideas parked intentionally

- Expanding the Pick'em view into a primary feature before the standard sportsbook trust baseline is stable.
- Broad dashboard redesign work that does not reduce reliability risk.
- Large refactors not directly tied to launch-critical behavior.
- New internal diagnostics surfaced to end users without a clear support workflow.

- [ ] Expand Journey Coach / tutorial content for EV education and bankroll basics. [Owner: Product/Frontend] [Target week: 2026-W19]
  - Why parked: Better educational content helps activation, but it should sit on top of a stable onboarding flow and trustworthy telemetry first.
  - User impact: High later.
  - Engineering risk: Low.
  - Next step: Draft the educational copy for fair odds, bankroll management, and weighted-median intuition after Journey Coach persistence and analytics are stable.
  - Codex fit: High.

These are not rejected forever; they are intentionally parked to prevent launch-risk dilution.

## What we are explicitly not doing right now

- We are not expanding feature scope ahead of trust-critical fixes.
- We are not rolling out paid tiers before reliability baseline is stable.
- We are not productizing internal/admin tools without a clear user-value and risk model.
- We are not doing broad architecture refactors during launch hardening.
