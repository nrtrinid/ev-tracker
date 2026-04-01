# Production deploy (VPS)

## Normal deploy

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

## Env var change

```bash
cd ~/ev-tracker
docker compose up -d --force-recreate backend_api backend_scheduler caddy
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
