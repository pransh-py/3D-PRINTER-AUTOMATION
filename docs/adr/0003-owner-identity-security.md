# ADR 0003: Owner Provisioning, MFA, and Authentication Audit

- Status: Accepted
- Date: 2026-07-17
- Owner: Codex root

## Context

Public buyer identity is implemented, but an `owner` role value alone is not an
authorization boundary. The one operational owner will approve money, change pricing,
and authorize a physical printer. Those actions require a separately provisioned owner,
multi-factor authentication, recent-authentication evidence, recovery, and durable audit
history before owner APIs are added.

## Owner provisioning decision

- Public registration continues to create only `buyer` accounts.
- The database contains one nullable `owner_slot`; the only valid owner value is
  `primary`, and a unique constraint permits at most one owner.
- The owner is created active and email-verified only through the interactive
  `xxx-api provision-owner` command. Passwords are read with `getpass`, never command-line
  arguments or environment variables.
- An existing buyer cannot be elevated by this command.
- `xxx-api reset-owner-mfa` is the deployment-access recovery procedure. It verifies the
  owner password, removes MFA material and recovery codes, consumes login challenges,
  revokes every session, and records an audit event.

## TOTP decision

- TOTP uses RFC 6238 defaults: SHA-1 compatibility, six digits, and 30-second steps.
- Validation accepts the current counter and one adjacent counter in either direction.
  A successful counter is persisted and cannot be accepted again.
- Each owner receives a random 160-bit secret. The secret is encrypted at rest with
  AES-256-GCM using a dedicated production secret and record-bound associated data.
- Enrollment requires an authenticated owner session, exact trusted origin, session-bound
  CSRF, and the current password. It returns the secret and provisioning URI once.
- Confirmation requires a valid TOTP. It enables MFA, marks the current session as
  MFA-authenticated, and returns ten one-time recovery codes once.
- Recovery codes carry 64 bits of randomness and are stored only as keyed digests.

## Owner login decision

- A buyer login and an owner login before initial MFA enrollment retain the existing
  successful session response.
- Once owner MFA is enabled, the password step returns `202` with a five-minute opaque
  one-time challenge and does not issue cookies.
- `POST /api/v1/auth/login/mfa` consumes that challenge plus either a TOTP or one recovery
  code, then issues the normal cookie session.
- MFA challenge and code attempts use shared Redis limits. Challenges and recovery codes
  cannot be replayed.

## Authorization decision

- Authentication returns a server-validated principal containing both the current user and
  refresh-session row.
- `require_owner` denies buyers regardless of client state or JWT role alone.
- `require_recent_owner_mfa` additionally requires enabled MFA and an MFA-authenticated
  session no older than the configured ten-minute window.
- Future payment verification, price overrides, refunds, printer commands, beneficiary
  changes, exports, and credential changes must use the recent-MFA dependency.

## Audit decision

- Authentication security transitions write append-only `audit_events` rows in the same
  database transaction as the state change.
- Events contain bounded event names, actor/target/session identifiers, request ID when
  available, timestamp, and reviewed non-secret JSON details.
- Passwords, raw tokens, TOTP secrets/codes, recovery codes, email addresses, IP addresses,
  and user-agent strings are never stored in audit details.

## Consequences

- Production must configure a distinct `XXX_MFA_ENCRYPTION_SECRET` of at least 32 bytes.
- Losing both the authenticator and all recovery codes requires deployment-level CLI
  recovery and signs out every device.
- TOTP is not phishing-resistant; a later WebAuthn authenticator can be added without
  weakening the owner-only and recent-authentication dependencies.
