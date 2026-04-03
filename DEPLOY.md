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

- API container: `APP_ROLE=api`, `ENABLE_SCHEDULER=1`, `UVICORN_WORKERS=2`
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

## Schema Parity Before Beta

Before a trusted-beta release, confirm production has:

- all numbered migrations through `database/migration_018_player_prop_model_weights_and_research_rls.sql`
- no outstanding schema changes that exist only under `backend/sql/`

Numbered migrations in `database/` are the canonical schema history. This repo still uses your current Supabase apply workflow, so apply any pending numbered files in order before calling the release ready.

## Env Var Change

After SSH'ing into the VPS:

```bash
cd ~/ev-tracker
docker compose up -d --force-recreate backend_api backend_scheduler caddy
```

## Health Checks

```bash
curl -i http://5.78.192.196/health
curl -i http://5.78.192.196/ready
```

## Ops Checks

```bash
curl -H "X-Ops-Token: $CRON_TOKEN" http://5.78.192.196/api/ops/status
curl -H "X-Ops-Token: $CRON_TOKEN" http://5.78.192.196/api/ops/clv-debug
curl -X POST -H "X-Ops-Token: $CRON_TOKEN" http://5.78.192.196/api/ops/trigger/test-discord
curl -X POST -H "X-Ops-Token: $CRON_TOKEN" http://5.78.192.196/api/ops/trigger/test-discord-alert
```

## Beta Env Checklist

Confirm these env values are present in the right place.

Backend / VPS:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `ODDS_API_KEY`
- `CRON_TOKEN`
- `OPS_ADMIN_EMAILS`
- `DISCORD_WEBHOOK_URL`
- `DISCORD_ALERT_WEBHOOK_URL`
- `DISCORD_DEBUG_WEBHOOK_URL`

Frontend / Vercel:

- `NEXT_PUBLIC_API_URL`
- `BACKEND_BASE_URL`
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `CRON_SECRET`
- `CRON_TOKEN`
- `OPS_ADMIN_EMAILS`
- `NEXT_PUBLIC_DISCORD_INVITE_URL`

## Security Note

Do not commit:

- private SSH keys
- passwords
- `.env` secrets
- raw ops tokens or cron tokens
