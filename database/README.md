# Database Workflow

The canonical schema history for this repo is the numbered migration chain in this directory:

- `migration_001_multi_tenant.sql`
- ...
- `migration_018_player_prop_model_weights_and_research_rls.sql`
- `migration_019_analytics_events.sql`
- `migration_020_beta_invite_code_access.sql`

## Source Of Truth

- Use `database/migration_*.sql` as the only authoritative schema history.
- Apply pending numbered migrations in order through your current Supabase workflow.
- Do not treat `backend/sql/` as part of normal bootstrap or deploy parity.

## Current State

- `database/schema.sql` is a legacy reference snapshot and may lag behind the live schema.
- `backend/sql/` contains legacy/manual SQL preserved for historical reference.
- New schema changes should land as a new numbered migration in `database/`.

## Applying Changes

For an existing environment:

1. Confirm the highest numbered migration already applied.
2. Apply each newer numbered migration in order.
3. Verify the app against `/health`, `/ready`, and the main logged-in flow.

For a new environment:

1. Start from the base schema already represented by the numbered chain.
2. Apply every numbered migration in order.
3. Do not apply ad hoc files from `backend/sql/` unless you are intentionally replaying legacy history.
