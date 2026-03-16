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
- The backend uses **Supabase Row Level Security (RLS)** to ensure users can only access their own data.
- All backend scan endpoints require a valid **Supabase JWT** for authentication.
- A per-user **rate limiter** (12 requests / 15 minutes) protects the scan endpoints from abuse.
- The `SUPABASE_SERVICE_ROLE_KEY` is only used server-side and never exposed to the browser.

## Dependency Security

This project uses standard dependency managers (pip for Python, npm for Node.js). We recommend enabling [Dependabot alerts](https://docs.github.com/en/code-security/dependabot) on your fork to stay notified of known vulnerabilities in dependencies.
