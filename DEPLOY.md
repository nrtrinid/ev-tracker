# Production deploy (VPS)

## SSH into the server

From your local machine:

```bash
ssh root@5.78.192.196
```

If the SSH host is not trusted yet, accept it when prompted.

After you are done on the server:

```bash
exit
```

## Normal deploy

After SSH'ing into the VPS:

```bash
cd ~/ev-tracker
git pull origin main
docker compose up -d --build
```

This deploy now runs two backend roles:
- `backend_api`: serves FastAPI traffic behind Caddy
- `backend_scheduler`: runs APScheduler jobs only

Recommended env:
- `APP_ROLE=api`, `ENABLE_SCHEDULER=1`, `UVICORN_WORKERS=2` for the API service
- `APP_ROLE=scheduler`, `ENABLE_SCHEDULER=1` for the scheduler service

## One-line deploy from your local machine

If your local machine already has SSH access configured for the VPS, you can run:

```bash
ssh root@5.78.192.196 "cd ~/ev-tracker && git pull origin main && docker compose up -d --build"
```

## Vercel env for the browser proxy cutover

Set these in Vercel preview and production:

```env
NEXT_PUBLIC_API_URL=/api/backend
BACKEND_BASE_URL=http://5.78.192.196
```

This keeps browser traffic same-origin through Next/Vercel while server-side bridge routes proxy to Hetzner directly. After you provision a real HTTPS backend hostname, keep `NEXT_PUBLIC_API_URL=/api/backend` and change only `BACKEND_BASE_URL`.

## Env var change

After SSH'ing into the VPS:

```bash
cd ~/ev-tracker
docker compose up -d --force-recreate backend_api backend_scheduler caddy
```

Or from your local machine:

```bash
ssh root@5.78.192.196 "cd ~/ev-tracker && docker compose up -d --force-recreate backend_api backend_scheduler caddy"
```

## Remove old/orphaned containers

If services were renamed and Docker reports orphans, run:

```bash
cd ~/ev-tracker
docker compose up -d --build --remove-orphans
```

## Health check

```bash
curl -i http://5.78.192.196/health
curl -i http://5.78.192.196/ready
```

## Ops checks

```bash
curl -H "X-Ops-Token: $CRON_TOKEN" http://5.78.192.196/api/ops/status
curl -H "X-Ops-Token: $CRON_TOKEN" http://5.78.192.196/api/ops/clv-debug
```

## Security note

Including the server IP and SSH username in this file is fine.

Do not commit:
- private SSH keys
- passwords
- `.env` secrets
- raw ops tokens or cron tokens
