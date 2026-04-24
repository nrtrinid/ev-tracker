# Production Deploy (VPS)

## SSH Into The Server

From your local machine:

```bash
ssh root@5.78.192.196
```

## Normal Deploy

After SSH'ing into the VPS:

```bash
cd ~/ev-tracker
git pull origin main
docker compose up -d --build
```

This deploy runs two backend roles:

- `backend_api`: serves FastAPI traffic behind Caddy
- `backend_scheduler`: runs APScheduler jobs only

Recommended env:

- API container: `APP_ROLE=api`, `ENABLE_SCHEDULER=0`, `UVICORN_WORKERS=2`
- scheduler container: `APP_ROLE=scheduler`, `ENABLE_SCHEDULER=1`

## One-Line Deploy From Local

```bash
ssh root@5.78.192.196 "cd ~/ev-tracker && git pull origin main && docker compose up -d --build"
```

## Vercel Env

Set these in preview and production:

```env
NEXT_PUBLIC_API_URL=/api/backend
BACKEND_BASE_URL=http://5.78.192.196
NEXT_PUBLIC_DISCORD_INVITE_URL=https://discord.gg/your-beta-invite
```

This keeps browser traffic same-origin through Next while server-side bridge routes still proxy to Hetzner directly.

When you set `BETA_INVITE_CODE`, prefer a short spoken phrase like `Daily Drop`. The app ignores case, spaces, and punctuation, so testers can type `daily drop`, `daily-drop`, or `dailydrop`.

## Schema Parity Before Beta

Before a trusted-beta release, confirm production has:

- all numbered migrations through `database/migration_023_player_prop_model_candidate_observations.sql`
- no outstanding schema changes that exist only in reference-only locations such as `database/schema.sql` or `backend/sql/`

Numbered migrations in `database/` are the canonical schema history. `database/schema.sql` and `backend/sql/` are legacy/reference-only and should not be used as deploy parity sources. This repo still uses your current Supabase apply workflow, so apply any pending numbered files in order before calling the release ready.

## Env Var Change

After SSH'ing into the VPS:

```bash
cd ~/ev-tracker
docker compose up -d --force-recreate backend_api backend_scheduler caddy
```

When Discord webhook values change, always run the force-recreate command above and then re-run the Discord verification checks below.

## Deploy Modes And Split-Role Safety

- Use `docker compose up -d --build` for code/image changes.
- Use `docker compose up -d --force-recreate backend_api backend_scheduler caddy` for environment changes.
- Always recreate `backend_api` and `backend_scheduler` together after env updates to avoid split-role drift.

Expected role/env alignment:

- `backend_api`: `APP_ROLE=api`, `ENABLE_SCHEDULER=0`
- `backend_scheduler`: `APP_ROLE=scheduler`, `ENABLE_SCHEDULER=1`

Quick verification after deploy:

```bash
docker compose config | grep -nE "backend_api|backend_scheduler|APP_ROLE|ENABLE_SCHEDULER"
```

## Health Checks

```bash
curl -i http://5.78.192.196/health
curl -i http://5.78.192.196/ready
docker compose ps backend_api backend_scheduler
```

Expected:

- `/health` returns `200` while the API process is alive.
- `/ready` returns `200` when Supabase env and DB connectivity are healthy.
- For API role, `scheduler_freshness` is advisory and should not fail readiness.
- For scheduler role, stale scheduler freshness should fail readiness.
- `backend_api` and `backend_scheduler` both report `healthy` in `docker compose ps`.

## Ops Checks

```bash
curl -H "X-Ops-Token: $CRON_TOKEN" http://5.78.192.196/api/ops/status
curl -H "X-Ops-Token: $CRON_TOKEN" http://5.78.192.196/api/ops/clv-debug
```

Use the release verification sequence below for trigger-based Discord checks.

## Discord Verification (Required)

Run this sequence after every deploy and every Discord secret rotation.
This is the canonical production verification sequence for health-sensitive release checks.

```bash
curl -X POST -H "X-Ops-Token: $CRON_TOKEN" http://5.78.192.196/api/ops/trigger/test-discord
curl -X POST -H "X-Ops-Token: $CRON_TOKEN" http://5.78.192.196/api/ops/trigger/test-discord-alert
curl -X POST -H "X-Ops-Token: $CRON_TOKEN" http://5.78.192.196/api/ops/trigger/board-refresh
curl -H "X-Ops-Token: $CRON_TOKEN" http://5.78.192.196/api/ops/status
```

Expected results:

- `test-discord` returns `ok: true` with a `run_id`
- `test-discord-alert` returns `ok: true` with a `run_id` and stays on debug/test routing
- ops board-refresh response includes `alerts_scheduled` and `alert_skip_totals`
- ops status runtime includes `discord.alert_delivery`, `discord.test_delivery`, and `discord.last_schedule_stats`
- backend logs include `[Discord] Webhook response: 2xx` and no repeated alert/debug webhook missing warnings

## Beta Env Checklist

Confirm these env values are present in the right place.
Use this section as the canonical env checklist for trusted-beta releases.

Backend / VPS:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `ODDS_API_KEY`
- `CRON_TOKEN`
- `BETA_INVITE_CODE`
- `OPS_ADMIN_EMAILS`
- `LIVE_TRACKING_ENABLED` (default `1`; set `0` to suppress `/bets/live` snapshots)
- `AUTO_SETTLE_SCORE_SOURCE` (default `provider_first`; set `odds_api` to force legacy score gating)
- `AUTO_SETTLE_PROVIDER_FALLBACK_TO_ODDS` (default `1`)
- `AUTO_SETTLE_PROVIDER_FINALITY_DELAY_MINUTES` (default `15`)
- `DISCORD_ENABLE_ALERT_ROUTE` (default `1`)
- `DISCORD_ALERT_WEBHOOK_URL` (scheduled board-drop alerts only)
- `DISCORD_DEBUG_WEBHOOK_URL`

Optional when alert-path delivery is intentionally enabled:

- `LIVE_TRACKING_PROVIDER_ORDER` (defaults to `espn,api_sports,odds_scores`)

Frontend / Vercel:

- `NEXT_PUBLIC_API_URL`
- `BACKEND_BASE_URL`
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `CRON_SECRET`
- `CRON_TOKEN`
- `BETA_INVITE_CODE`
- `OPS_ADMIN_EMAILS`
- `NEXT_PUBLIC_DISCORD_INVITE_URL`

## Security Note

Do not commit:

- private SSH keys
- passwords
- `.env` secrets
- raw ops tokens or cron tokens
