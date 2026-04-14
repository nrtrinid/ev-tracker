# Trusted Beta

This document is the short runbook for the friends-only trusted beta.

## What Testers Should Expect

- `main` is the beta branch and should feel stable enough to share.
- Signup should require the shared beta invite code once per account via `BETA_INVITE_CODE`.
- Use an easy spoken phrase for the invite code. The app ignores case, spaces, and punctuation, so `Daily Drop`, `daily-drop`, and `dailydrop` all work.
- The home page is driven by the daily board:
  - `Promos` mixes promo-ranked game lines and player props
  - `Game Lines` can include moneylines, spreads, and totals
  - `Player Props` includes curated sportsbook props plus the Pick'em board
- CLV is tracked when closes are captured successfully, but some bets may still show no CLV if the close could not be recovered.

## Feedback Flow

Discord is the primary beta support channel.

Suggested structure:

- `#beta-feedback` for user reactions and bugs
- `#beta-alerts` for board-drop notifications
- `#beta-debug` or `#ops` for test/debug/heartbeat traffic

Recommended routing:

- `DISCORD_ALERT_WEBHOOK_URL` -> alert/beta-alerts channel for the `10:30` and `15:30` board drops
- `DISCORD_DEBUG_WEBHOOK_URL` -> debug/ops channel
- `DISCORD_WEBHOOK_URL` -> fallback only

The app can expose the invite link through `NEXT_PUBLIC_DISCORD_INVITE_URL`.

## Intentionally Rough / Still Evolving

- Market coverage still changes by slate and daily-drop composition.
- CLV reliability is improving, especially for player props, and should be watched closely after releases.
- Pick'em validation is new and needs sample size before the metrics become decision-grade.
- Some documentation remains operationally important because the product is moving faster than a fully packaged onboarding flow.

## Release Prerequisites

Use [DEPLOY.md](../DEPLOY.md#beta-env-checklist) as the canonical source for:

- backend/frontend release env values
- migration parity through the numbered `database/migration_*.sql` chain

## Launch-Day Checklist

1. Deploy `main` to Vercel and Hetzner.
2. Run [DEPLOY.md](../DEPLOY.md#discord-verification-required) and confirm all checks pass.
3. Confirm the production routes needed for tester support (`/health`, `/ready`, `/api/ops/status`) are healthy.
4. Use a fresh beta account and verify:
   - sign up / sign in
   - home board loads
   - promos, game lines, and player props are understandable
   - a bet can be logged
   - settings and analytics load
5. Log at least one straight bet and one player prop if possible.

## First 24-48 Hours

- Watch Discord feedback for repeated confusion around:
  - what `Promos` means
  - what `Game Lines` means
  - what Pick'em percentages mean
  - why some bets may not have CLV yet
- Review ops for:
  - readiness degradation
  - Discord delivery failures
  - CLV missing and invalid-close buckets
  - stale board snapshots or scan freshness problems
