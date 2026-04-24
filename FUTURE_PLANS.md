# FUTURE_PLANS

Last updated: 2026-04-23
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

- [x] Apply duplicate-state tags consistently across all scanner cards (not only player props): `Already Placed`, `Placed Elsewhere`, and `Better Now`. [Owner: Backend/Frontend] [Completed: 2026-04-22]
  - Why: Duplicate labels influence logging and exposure decisions; inconsistent card tagging breaks user trust quickly.
  - User impact: High.
  - Engineering risk: Medium.
  - Completed work: Consolidated duplicate annotation through the shared backend scanner duplicate service, extended straight-bet matching beyond moneyline with v2 selection identity plus legacy ML fallback, and updated scanner badges so `logged_elsewhere` renders as `Placed Elsewhere`.
  - Regression coverage: Added backend unit coverage for moneyline, spread, total, cross-book, and prop duplicate states, plus frontend scanner duplicate-state coverage for all three badges across straight-bet and player-prop cards.
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
  - Follow-up: Extend the same normalization pattern to any remaining active beta book/market shapes that still diverge from the standard paired-line representation, especially alternate markets like pitcher strikeouts that still need the same ladder-to-paired-line matching support total bases now has.
  - Codex fit: Extremely high.

- [x] Canonicalize beta telemetry, attribution, and event dedupe. [Owner: Frontend/Backend] [Completed: 2026-04-22]
  - Why: Current beta analytics can show dropped funnels (`tutorial_completed=Unknown`, `board_viewed=Unknown`), impossible conversion math, and likely duplicate firing on `bet_logged`. Without canonical event definitions, idempotency, and source attribution, beta product decisions are noisy.
  - User impact: Low direct, critical for product direction and operator trust.
  - Engineering risk: Low to medium.
  - Completed work: Canonicalized analytics property enrichment and session/user-safe dedupe handling, flagged internal/test accounts via allowlists, and defaulted ops analytics summary/user drilldown to external tester signal with explicit excluded-count and quality-warning context.
  - Regression coverage: Added backend analytics service/reporting coverage for canonicalization, audience filtering, and funnel ordering invariants, plus frontend analytics bridge timeout/access coverage for summary/users routes.
  - Codex fit: High.

- [x] Expand board route contract coverage for latest modes, surface endpoint, and scoped refresh behavior. [Owner: Backend] [Completed: 2026-04-24]
  - Why: Board routes are complex and central to first impression reliability.
  - User impact: High.
  - Engineering risk: Medium.
  - Completed work: Confirmed existing route-level coverage for latest-board modes, surface endpoint success/error branches, rate limits, invalid scopes, scoped refresh failures, and player-prop scoped refresh success.
  - Regression coverage: Added straight-bets scoped refresh success coverage proving supported sports are merged, scoped cache persistence is used, pick'em sync is skipped, and `last_board_refresh` remains scoped/non-canonical.
  - Codex fit: High.

- [x] Ensure daily-board pipeline card reflects the latest ops manual refresh state (no stale board status after manual refresh). [Owner: Backend/Frontend] [Completed: 2026-04-21]
  - Why: Operators report cases where manual refresh succeeds but the board pipeline card still shows stale state.
  - User impact: High (trust in board freshness and operator confidence).
  - Engineering risk: Medium.
  - Completed work: Added normalized `last_board_refresh` ops status across board-drop and scoped-refresh paths, persisted scoped refreshes into durable ops history without republishing canonical `board:latest`, and updated the ops dashboard to poll short-term after async refresh acceptance so the cards settle without waiting for the next background refetch window.
  - Regression coverage: Added backend tests for scoped-refresh success/failure status persistence plus ops-history selection of the freshest board-affecting refresh, and updated scheduler/ops-trigger status assertions.
  - Follow-up: Resolved follow-up coverage and scheduled board-drop recency verification on 2026-04-24.
  - Codex fit: High.

- [ ] Audit deeplink reliability and fallback behavior by sportsbook/platform. [Owner: Frontend/Product/Ops] [Target week: 2026-W18]
  - Why: Finding an edge is not enough if the handoff to the sportsbook is unreliable. App-vs-web, geo-plugin, and platform-specific friction can make a "working" deeplink practically unusable.
  - User impact: High.
  - Engineering risk: Medium.
  - Next step: Build a per-book matrix across desktop/mobile/app, verify expected fallback behavior, and add per-book UI hints or graceful fallback copy where direct reachability is weak.
  - Codex fit: Good for the matrix and fallback implementation; final QA needs human validation.

- [x] Fix Discord notification route separation so heartbeat/test traffic does not keep falling back onto the alert webhook path. [Owner: Backend/Ops] [Completed: 2026-04-24]
  - Why: The intended Discord notification path split still does not appear to be working in production behavior; notifications are still arriving through the alert path, which weakens signal separation and makes ops routing harder to trust.
  - User impact: Medium for operators, indirect but important for reliability monitoring.
  - Engineering risk: Medium.
  - Completed work: Enforced strict Discord route separation so only scheduler-owned alert contexts may use the alert path; heartbeat, test, manual refresh, and unknown traffic now require the debug webhook or return unconfigured diagnostics.
  - Regression coverage: Added Discord service and ops trigger coverage proving the legacy fallback env no longer routes heartbeat/test/manual traffic to the alert webhook, while scheduled board-drop alert delivery remains supported.
  - Codex fit: High.

- [x] Fix scheduled board drop recency on the ops page so the card reflects actual successful runs. [Owner: Backend/Frontend/Ops] [Completed: 2026-04-24]
  - Why: The scheduled board drop appears to still be running twice daily, but the ops page can show a stale last-run timestamp from days ago. That creates false alarm fatigue and makes it hard to trust the scheduler health view.
  - User impact: Medium for operators, high for trust in operational visibility.
  - Engineering risk: Medium.
  - Completed work: Reconciled durable ops history with live in-memory ops status so the fresher scheduler, ops-trigger, or board-refresh timestamp wins instead of stale durable rows always overwriting live state.
  - Regression coverage: Added ops-history tests proving fresh live board status wins over stale durable rows and newer durable rows still win over older live fallback state.
  - Codex fit: High.

- [x] Re-add CLV piggyback on admin-triggered scans for currently placed bets with CLV pending (not only JIT scheduler job coverage). [Owner: Backend] [Completed: 2026-04-21]
  - Why: CLV pending bets can miss timely updates when only the JIT path runs; admin-triggered scans should also advance CLV snapshots.
  - User impact: Medium to high (faster CLV visibility on active bets).
  - Engineering risk: Medium.
  - Completed work: Admin-triggered board refresh now piggybacks `main._piggyback_clv` on successful board-drop runs using only fresh sides returned by `run_daily_board_drop` (`fresh_straight_sides` + `fresh_prop_sides`), and scheduled board-drop runs now use the same fresh-side piggyback path.
  - Regression coverage: Added backend ops-trigger contract coverage for sync/async piggyback wiring, empty fresh-side skip behavior, and best-effort failure isolation when piggyback execution raises, plus scheduler coverage for scheduled board-drop piggyback invocation and failure isolation.
  - Follow-up: Keep the existing JIT CLV scheduler path unchanged as the safety-net close-line refresher, but re-open verification because current placed-bet CLV pills still appear stale after board update scans in some cases even after the piggyback wiring landed.
  - Codex fit: High.

- [ ] Fix CLV refresh parity between board update scans and placed-bet UI state. [Owner: Backend/Frontend] [Target week: 2026-W18]
  - Why: We already re-added CLV piggyback on board update scans, but currently placed bets can still keep stale CLV pending/display pills after those scans complete. That makes users think CLV capture did not run, even when backend scan plumbing may have fired.
  - User impact: High for trust in bet tracking and CLV reporting.
  - Engineering risk: Medium.
  - Next step: Trace the full path from board-refresh piggybacked CLV capture through persistence, bet-query serialization, and frontend invalidation/rendering so placed-bet CLV pills update immediately after a successful scan instead of waiting for some later refresh path.
  - Codex fit: High.

- [ ] Add spread auto-settle support and regression coverage. [Owner: Backend] [Target week: 2026-W18]
  - Why: Spread bets do not appear to settle automatically today, which leaves a common straight-bet type dependent on manual cleanup and weakens trust in the tracker.
  - User impact: High.
  - Engineering risk: Medium.
  - Next step: Audit the current auto-settle market/result matching path for spread bets, implement the missing line/outcome handling, and add targeted regression tests so spread wagers settle with the same reliability expectations as moneylines/totals where supported.
  - Codex fit: High.

- [ ] Design a sportsbook settlement reconciliation layer to make bankroll tracking penny-perfect, starting with DraftKings and FanDuel. [Owner: Backend/Ops] [Target week: 2026-W18]
  - Why: We are still seeing small bankroll mismatches versus real sportsbook balances. FanDuel exposed missing-settlement/state gaps, while DraftKings appears to have cents-level payout-rounding differences. This is trust-critical because even small bankroll drift makes users question every downstream balance, EV, and P&L number.
  - User impact: High.
  - Engineering risk: Medium to high.
  - Scope guardrails: Treat this as a deterministic reconciliation and rule-inference problem, not an RL problem. Use integer cents plus `Decimal`, keep the system auditable, and prefer a narrow reconciliation layer over a broad settlement-system rewrite.
  - Planning target: Produce a repo-grounded implementation plan first, covering current bankroll calculation paths, settlement fields/models, any external bet-id support, profit/payout helpers, admin/manual logging flows, and existing tests/scripts related to bankroll or settlement.
  - Required design shape:
    - Trust actual sportsbook payout amounts as the top-priority source of truth when available.
    - When actual payout is unavailable, infer sportsbook-specific settlement rules from historical settled bets.
    - If a case is weird or low-confidence (promo edge case, early payout, unsupported settlement pattern, partial/manual ambiguity), flag it for manual reconciliation instead of pretending certainty.
  - Required deliverables:
    - A concrete implementation plan for a rounding-rule inference harness and reconciliation workflow.
    - Candidate-rule evaluation across sportsbook/promo/odds-sign segments, scored by exact-match rate and total cents error.
    - A script/CLI plan to ingest historical settled bets with actual sportsbook payout amounts, test candidate formulas, discover best-fit rules, and export mismatches for audit.
    - Data-model recommendations for fields like `sportsbook_settlement_amount_cents`, `sportsbook_balance_after_cents`, `sportsbook_txn_id`, `settlement_confidence`, and `settlement_source` (`actual_book`, `inferred_rule`, `manual`).
    - A rollout plan that starts with the smallest safe slice and keeps manual logging plus unsupported markets auditable.
  - Next step: Do a repo inspection and write the detailed implementation plan only; do not implement production reconciliation logic until the plan is reviewed.
  - Codex fit: High for repo audit, deterministic rule-harness design, script/test planning, and phased rollout proposal.

- [x] Resolve release/docs/runtime parity drift across status docs. [Owner: Docs] [Completed: 2026-04-22]
  - Why: Inconsistent release metadata causes operator confusion and weakens launch discipline.
  - User impact: Medium (operator-facing, but impacts release confidence).
  - Engineering risk: Low.
  - Completed work: Aligned README, PROJECT env reference, HANDOFF, CHANGELOG, and this roadmap with the current trusted-beta baseline and telemetry hardening status.
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

- [ ] Surface total balance in the global header and allow deposit/withdraw logging from anywhere. [Owner: Frontend] [Target week: 2026-W19]
  - Why: Total balance is a core piece of user state, and deposit/withdraw logging is too buried under `More` -> `Settings` for an action users may want frequently. A global entry point would reduce friction and make bankroll management feel like a first-class workflow.
  - User impact: Medium to high.
  - Engineering risk: Low to medium.
  - Next step: Add a compact top-right balance chip/button in the shared header, open a lightweight balance panel or modal with the current total plus `Deposit` / `Withdraw` actions, and keep the deeper settings page for full balance management details.
  - Codex fit: High.

- [ ] Add internal coverage diagnostics for partial or unsupported book/market combinations. [Owner: Backend/Ops] [Target week: 2026-W19]
  - Why: It is currently too easy to confuse true market absence, delayed population, one-sided ladder evidence, and parsing failure. Operators need to know which case they are looking at.
  - User impact: Medium.
  - Engineering risk: Medium.
  - Next step: Surface a small internal support matrix or reason code (`unsupported`, `not_yet_populated`, `one_sided_only`, `parse_failed`) for key book/market paths.
  - Codex fit: High.

- [ ] Extend alt-line equivalency matching beyond total bases to other supported markets such as pitcher strikeouts. [Owner: Backend] [Target week: 2026-W19]
  - Why: We already solved this for total bases, but other alt markets still risk missing edges or failing fair-odds comparisons when books express the same threshold as ladder-style `2+`, `3+`, etc. instead of paired over/under lines.
  - User impact: Medium to high.
  - Engineering risk: Medium.
  - Next step: Reuse the total-bases canonicalization pattern for pitcher strikeouts and other active alt markets, then add focused parsing/comparison regression tests for mixed ladder vs paired-line books.
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
