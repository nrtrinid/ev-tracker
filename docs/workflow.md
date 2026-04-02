# Workflow

This project moves fastest when `main` stays boring.

## Branches

- `main`
  - stable branch
  - safe to share with beta testers
  - the only branch that should feed public Vercel and Hetzner deploys
- `dev`
  - daily work branch
  - safe place for in-progress features, refactors, and deployment experiments

For larger efforts, branch from `dev`.

## Recommended Solo Workflow

1. Start work from `dev`.
2. Make changes locally.
3. Verify locally before pushing.
4. Push to `dev` while iterating.
5. Promote to `main` only when the current state is acceptable for invited testers.
6. Let Vercel and Hetzner deploy from `main`.

## Release Rule

- Push to `dev` whenever you want.
- Push to `main` only when you would be comfortable with a friend testing it immediately.

For trusted beta, also assume:

- docs and changelog should describe the actual tester-facing behavior on `main`
- database migrations and env changes should land before or alongside the release
- Discord feedback and alert routing should be tested in the real environment before sharing the build

## Minimal Pre-Merge Checklist

Before promoting `dev` into `main`, verify:

- no obvious console errors
- no backend startup errors
- home page loads
- `/scanner/straight_bets` loads and scans
- `/scanner/player_props` loads and the `Sportsbooks` / `Pick'em` split is clear
- `/parlay` loads and can hand off cleanly to the tracker
- `/settings` and `/more` load

If the change touches automation, ops, CLV, or Discord:

- `/ready` returns healthy
- ops trigger endpoints still respond correctly
- both Discord validation routes still work
- the in-app beta feedback entry still points to the correct Discord invite

If the change materially affects tester behavior:

- update `README.md`
- update the relevant docs
- update `CHANGELOG.md`

## Deployment Advice

If possible, keep two environments:

- stable beta deployment from `main`
- personal preview/dev deployment from `dev`

If you only keep one deployment, it should track `main`, not `dev`.

## Notes

- do not commit local `.env` files
- rotate any secret that was pasted into logs, screenshots, or chat history
- do not rely on generated local build artifacts
- if you hotfix production from `main`, back-merge into `dev`
