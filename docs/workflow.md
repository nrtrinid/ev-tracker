# Workflow

This project moves fastest when `main` stays boring.

## Branches

- `main`
  - Stable branch
  - Safe to share with testers
  - The only branch that should auto-deploy to the public Vercel and Render apps
- `dev`
  - Daily work branch
  - Safe place for in-progress features, refactors, and deployment experiments

For larger efforts, branch from `dev`:

- `feature/player-props-polish`
- `feature/parlay-preview`
- `fix/discord-diagnostics`

## Recommended Solo Workflow

1. Start work from `dev`.
2. Make changes locally.
3. Verify locally before pushing:
   - frontend loads
   - backend boots
   - login works
   - scanner works
   - player props works if touched
   - parlay cart works if touched
4. Push to `dev` while iterating.
5. Merge `dev` into `main` only when the current state is acceptable for testers.
6. Let Vercel and Render deploy from `main`.

## Release Rule

Use this rule of thumb:

- Push to `dev` whenever you want.
- Push to `main` only when you would be comfortable with a friend testing it immediately.

That keeps beta reports consistent and prevents testers from landing on half-finished deploys.

## Minimal Pre-Merge Checklist

Before merging `dev` into `main`, verify:

- No obvious console errors
- No backend startup errors
- Home page loads
- `/scanner/straight_bets` loads and scans
- `/scanner/player_props` loads, shows diagnostics, and makes it clear whether filters or the quality gate hid results
- `/parlay` loads and retains cart state
- `/settings` loads

If the change touches automation or ops:

- `/ready` returns healthy
- ops trigger endpoints still respond correctly

## Deployment Advice

If possible, keep two environments:

- Stable production/beta deployment from `main`
- Personal preview/dev deployment from `dev`

If you only keep one deployment for now, it should track `main`, not `dev`.

## Notes

- Do not commit local `.env` files.
- Rotate any secret that was pasted into logs, screenshots, or chat history.
- Do not rely on `frontend/tsconfig.tsbuildinfo`; it is generated and ignored.
- If you need to hotfix production, branch from `main`, fix locally, merge to `main`, then back-merge into `dev`.
