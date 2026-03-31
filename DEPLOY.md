# Production deploy (VPS)

## Normal deploy

```bash
cd ~/ev-tracker
git pull origin main
docker compose up -d --build
```

## Env var change

```bash
cd ~/ev-tracker
docker compose up -d --force-recreate backend caddy
```

## Health check

```bash
curl -i http://5.78.192.196/health
```
