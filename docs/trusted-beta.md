# Trusted Beta

This document is the short runbook for the friends-only trusted beta.

## What Testers Should Expect

- `main` is the beta branch and should feel stable enough to share.
- Signup is open, but distribution is invite-only.
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

## Beta Env Checklist

Before release, confirm:

- Backend / VPS
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `ODDS_API_KEY`
  - `CRON_TOKEN`
  - `OPS_ADMIN_EMAILS`
  - `DISCORD_WEBHOOK_URL`
  - `DISCORD_ALERT_WEBHOOK_URL`
  - `DISCORD_DEBUG_WEBHOOK_URL`
- Frontend / Vercel
  - `NEXT_PUBLIC_API_URL`
  - `BACKEND_BASE_URL`
  - `NEXT_PUBLIC_SUPABASE_URL`
  - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
  - `CRON_SECRET`
  - `CRON_TOKEN`
  - `OPS_ADMIN_EMAILS`
  - `NEXT_PUBLIC_DISCORD_INVITE_URL`
- Database
  - all numbered migrations through `database/migration_018_player_prop_model_weights_and_research_rls.sql`
  - no pending schema changes that exist only under `backend/sql/`

## Launch-Day Checklist

1. Deploy `main` to Vercel and Hetzner.
2. Confirm `/health` and `/ready`.
3. Confirm `/api/ops/status` and `/api/ops/clv-debug`.
4. Trigger:
   - `POST /api/ops/trigger/test-discord`
   - `POST /api/ops/trigger/test-discord-alert`
  - Confirm both return `ok: true` and include a `run_id`
  - Confirm backend logs show `[Discord] Webhook response: 2xx`
5. Use a fresh beta account and verify:
   - sign up / sign in
   - home board loads
   - promos, game lines, and player props are understandable
   - a bet can be logged
   - settings and analytics load
6. Log at least one straight bet and one player prop if possible.

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
