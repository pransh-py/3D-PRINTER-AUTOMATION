# ADR 0002: Identity HTTP, Email, and Rate-Limit Adapters

- Status: Accepted
- Date: 2026-07-17
- Owner: Codex root

## Context

ADR 0001 established identity storage and session security. Public browser routes now need a contract that does not expose bearer tokens, permit cross-site state changes, leak account eligibility through response bodies/status codes, or allow password hashing and email delivery to be abused without shared limits.

The production sender domain and SMTP provider remain stakeholder deployment inputs. Mailpit is the approved local-development SMTP target.

## Deployment decision

Production exposes Next.js and `/api/v1` under one browser origin through a reverse proxy. The FastAPI service, PostgreSQL, Redis, and SMTP credentials remain private infrastructure. Host-only cookies never set a parent `Domain` attribute.

Development uses `localhost:3000` for Next.js and `localhost:8000` for FastAPI. Cookies are host-scoped rather than port-scoped, so this preserves the same browser behavior while keeping the services independently runnable.

## Public identity contract

All state-changing endpoints accept JSON, require an exact configured `Origin`, reject `Sec-Fetch-Site: cross-site`, and return `Cache-Control: no-store`.

| Method | Path | Result |
| --- | --- | --- |
| `POST` | `/api/v1/auth/register` | `202`; generic eligibility message |
| `POST` | `/api/v1/auth/resend-verification` | `202`; same generic message |
| `POST` | `/api/v1/auth/verify-email` | Consumes a token from a JSON body |
| `POST` | `/api/v1/auth/login` | Safe user profile plus session cookies |
| `POST` | `/api/v1/auth/refresh` | `204`; rotates cookies after CSRF validation |
| `POST` | `/api/v1/auth/logout` | `204`; revokes the family and clears cookies |
| `GET` | `/api/v1/auth/me` | Safe authenticated profile only |
| `POST` | `/api/v1/auth/forgot-password` | `202`; same generic eligibility message |
| `POST` | `/api/v1/auth/reset-password` | Consumes a token and revokes all sessions |

Registration has no role field. It creates only `buyer`; owner provisioning remains administrative.

## Cookie and CSRF decision

- Access: HTTP-only, SameSite Lax, path `/`, 15-minute maximum age.
- Refresh: HTTP-only, SameSite Strict, path `/api/v1/auth`, with the server-side family's absolute expiry.
- CSRF: readable, SameSite Lax, path `/`, with the same absolute family expiry.
- Production access/CSRF names use `__Host-`; the path-scoped refresh name uses `__Secure-`.
- Refresh and logout require exact origin plus a signed double-submit CSRF value bound to the current persisted session ID.
- Authentication responses never contain access, refresh, or CSRF bearer values in JSON.

## Email decision

The API uses a provider-neutral SMTP adapter. Mailpit at `127.0.0.1:1025` is the development default. Production startup rejects the example sender, HTTP public URL, and local Mailpit coordinates.

Verification and reset links carry the one-time token in the URL fragment (`#token=...`), which browsers do not send in HTTP requests or referrer headers. The frontend will explicitly move that value into the POST JSON body.

Registration, resend, and forgot-password responses are identical for eligible and ineligible addresses. SMTP failure is recorded without recipient/token/provider details and does not change that public response. Users may retry through the bounded resend/request endpoints.

## Rate-limit decision

Redis is the shared fail-closed limiter. A Lua script atomically increments and expires every layered counter. Redis keys contain an HMAC digest, never raw email addresses, IP addresses, refresh tokens, or one-time tokens.

- Email actions: IP limit of 10 per 15 minutes and normalized-email limit of 3 per hour.
- Login: IP limit of 10 per 15 minutes and normalized-email limit of 5 per hour.
- Verification/reset token consumption: IP limit of 20 per 15 minutes and token limit of 10 per 15 minutes.
- Refresh/logout: IP limit of 20 per 15 minutes and refresh-token limit of 30 per 15 minutes.
- Redis unavailability returns `503`; exceeded limits return `429` with `Retry-After`.

## Consequences

- The API can scale horizontally without per-process rate-limit gaps.
- A stolen refresh cookie alone is insufficient for refresh/logout because the signed CSRF proof is separate and session-bound.
- Production deployment must provide a real HTTPS web origin, sender address, and non-development SMTP transport.
- Email delivery remains synchronous for the MVP; a later encrypted transactional notification pipeline may replace it without changing the public contract.
