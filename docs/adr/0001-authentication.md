# ADR 0001: Authentication and Session Persistence

- Status: Accepted
- Date: 2026-07-17
- Owner: Codex root

## Context

The public application has two roles: `buyer` and `owner`. Buyers register publicly; owner accounts are provisioned administratively. The web and API are separate services, and the platform handles private model files, manual payment verification, and physical printer actions. Session compromise therefore has direct privacy, financial, and physical consequences.

## Decision

- Normalize email addresses for lookup and enforce database uniqueness.
- Hash passwords with Argon2id through `pwdlib`; never store or log plaintext passwords.
- Issue 15-minute JWT access tokens signed with HS256 by the single API service. Require issuer, audience, subject, session ID, role, token type, issued-at, not-before, expiry, and JWT ID claims.
- Store access tokens only in secure HTTP-only cookies. Do not persist them in browser storage or the database.
- Use 256-bit opaque refresh tokens with a 30-day absolute family lifetime. Store only an HMAC-SHA-256 digest, rotate on every use without extending that lifetime, and track a session family. Reuse of a rotated token revokes the entire family.
- Bind access tokens to a persisted refresh-session ID so revocation and user-status checks can invalidate a session.
- Bound active session families per user; creating a session beyond the configured limit revokes the oldest active family.
- Use independent 256-bit opaque one-time tokens for email verification and password reset. Store only digests, purposes, expiry, and consumption state.
- Protect cookie-authenticated state changes with a signed double-submit CSRF token bound to the persisted session ID and checked using constant-time comparison.
- Require verified email before normal buyer login. Disabled users and revoked sessions fail closed.
- Create owner accounts only through an explicit administrative operation. Owner MFA is a required later gate before payment verification or printer control.
- Use SQLAlchemy 2 async sessions scoped to one request/task and Alembic-reviewed migrations.

## Cookie policy

- Access cookie: HTTP-only, Secure in production, SameSite=Lax, path `/`.
- Refresh cookie: HTTP-only, Secure in production, SameSite=Strict, path `/api/v1/auth`.
- CSRF cookie: readable by the web application, Secure in production, SameSite=Lax, path `/`.
- Cookies use the `__Host-` prefix in production deployments that satisfy its requirements.

## Secrets

Production requires separate high-entropy values for JWT signing and opaque-token HMAC. Development defaults are visibly unsafe and rejected when `environment=production`. Secrets are never included in logs, exceptions, API responses, migrations, or source control.

## Consequences

- Refresh and one-time tokens can be revoked and audited without storing bearer credentials.
- Every authenticated request still performs appropriate user/session status checks; a valid JWT alone is not sufficient for privileged actions.
- Cross-site cookie behavior requires explicit CSRF and Origin validation.
- Horizontal scaling is safe because session truth lives in PostgreSQL rather than process memory.
- Email delivery, rate limiting, MFA enrollment/recovery, and route integration remain separate reviewed milestones.
