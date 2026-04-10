# Secrets And Rotation

This repo keeps live secrets in local env files only. They should never be committed.

## Files that must stay local

- `backend/.env`
- `frontend/.env.local`

Template files such as `backend/.env.example` and `frontend/.env.example` are safe to commit because they contain placeholders only.

## Rotation checklist

If a secret was exposed in logs, screenshots, chat history, or a pasted env file, rotate it rather than assuming it is still safe.

Recommended priority:

1. `SUPABASE_SERVICE_ROLE_KEY`
2. `ODDS_API_KEY`
3. `CRON_TOKEN`
4. Discord webhook URLs (`DISCORD_WEBHOOK_URL`, `DISCORD_ALERT_WEBHOOK_URL`, `DISCORD_DEBUG_WEBHOOK_URL`)

After rotation:

1. Update `backend/.env` and `frontend/.env.local`.
2. Restart local services so they pick up the new values.
3. Redeploy any hosted environments that still hold the old values.
4. Test backend boot, manual scans, ops token routes, and Discord test routes if used.

## Quick local git hygiene checks

Run these from the repo root:

```powershell
.\scripts\secret-hygiene-check.ps1
git check-ignore backend/.env frontend/.env.local
git ls-files backend/.env frontend/.env.local
git diff --cached --name-only
```

What you want to see:

- env files are ignored
- env files are not tracked
- no secret-bearing files are staged

## Repo hygiene rules

- Never paste real secrets into docs, fixtures, or examples.
- Never commit real webhook URLs.
- `BETA_INVITE_CODE` and `OPS_ADMIN_EMAILS` are configuration values, but they still belong in env files rather than source.
- `NEXT_PUBLIC_DISCORD_INVITE_URL` is intentionally public-facing; do not treat it like a secret.
- Prefer placeholders in `.env.example`.
- If a credential was shared anywhere outside your local machine, assume rotation is required.
