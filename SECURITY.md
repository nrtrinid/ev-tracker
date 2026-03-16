# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| latest (main) | ✅ |

## Reporting a Vulnerability

If you discover a security vulnerability in EV Betting Tracker, please **do not open a public GitHub issue**.

Instead, report it privately by emailing the maintainer directly (contact info in GitHub profile) or by using [GitHub's private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability) if enabled on this repo.

Please include:
- A description of the vulnerability
- Steps to reproduce or a proof-of-concept
- The potential impact

You can expect an acknowledgment within 48 hours and a resolution timeline within 7 days for critical issues.

## Security Practices in This Repo

- All secrets (Supabase keys, Odds API key) are managed via `.env` files and are **never committed to the repository**.
- The `.gitignore` explicitly excludes `.env`, `.env.local`, and `.env.*.local`.
- **Authentication** is handled via [Supabase Auth](https://supabase.com/docs/guides/auth). Every protected endpoint extracts the `Bearer` token from the `Authorization` header and validates it by calling `supabase.auth.get_user(token)` via the Supabase Python SDK. Invalid or expired tokens return HTTP 401.
- **Multi-tenant data isolation** is enforced at the query level. The backend uses the service role key (which bypasses Supabase RLS), so every database query explicitly scopes results to the authenticated user with `.eq("user_id", user["id"])`. No user can read or modify another user's data.
- A per-user **rate limiter** protects the scan endpoints (`/api/scan-bets` and `/api/scan-markets`) from abuse. Limits: **12 requests per 15-minute window per user**. Violations return HTTP 429. The limiter is in-memory and resets on server restart — all other API routes (bets, balances, settings, etc.) are not rate limited.
- The `SUPABASE_SERVICE_ROLE_KEY` is only used server-side (`backend/.env`) and is never exposed to the browser.

## Dependency Security

This project uses standard dependency managers (pip for Python, npm for Node.js). We recommend enabling [Dependabot alerts](https://docs.github.com/en/code-security/dependabot) on your fork to stay notified of known vulnerabilities in dependencies.
