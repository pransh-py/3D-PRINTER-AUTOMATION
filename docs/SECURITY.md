# `xxx` Security and Safety Baseline

## Security objectives

1. A buyer can access only their own identity, models, quotations, payments, orders, and fulfillment data.
2. Only the owner can approve prices, verify payments, manage queues, or authorize physical printer actions.
3. Untrusted model files cannot execute code, reach secrets, access other files, or control the printer.
4. A payment claim cannot become a paid order without independent verification.
5. Retries, duplicate requests, stale pages, or network recovery cannot start duplicate prints or duplicate business transitions.
6. Security-relevant actions remain attributable and recoverable.

## Threat boundaries

- Public browser and API traffic is hostile by default.
- Uploaded models, metadata, filenames, archives, previews, and slicer output are untrusted.
- Buyer-submitted UTRs and screenshots are unverified claims.
- The Windows bridge may be offline, stale, compromised, or connected to unexpected firmware.
- The printer is a physical actuator; logical authorization does not prove the bed/material/nozzle is safe.
- Owner credentials are high-value because there is one operational account.

## Authentication and authorization

- Normalize and verify email ownership; prevent enumeration in registration/reset responses.
- Hash passwords with Argon2id; apply breached/common-password checks without sending passwords to third parties.
- Rate-limit login, registration, verification, reset, MFA, upload creation, quote acceptance, and payment claims by layered identifiers.
- Use short access-token lifetimes, rotated refresh sessions, secure HTTP-only cookies, CSRF protection, and server-side revocation.
- Require MFA and recent authentication for owner payment verification, price overrides, refunds, printer actions, UPI-beneficiary changes, exports, and credential changes.
- Enforce role and resource ownership in domain/service code and database queries, not only routes or UI.
- Deny by default. Keep an authorization test matrix covering both roles and cross-buyer access attempts.

## Manual UPI controls

- Never mark paid from a browser redirect, screenshot, UTR shape, QR scan, or buyer request.
- Owner verification must compare beneficiary, amount, reference, and received/settled state in the actual account.
- Unique constraints and audit alerts detect duplicate UTR/reference submissions; owner adjudication remains necessary.
- UPI beneficiary changes require owner MFA, show a confirmation summary, create a new version, and never alter existing payment intents.
- Do not expose full bank details beyond what is required for payment.
- Payment evidence is private, access-logged, malware-scanned, and deleted according to the retention policy.

## Upload and slicing controls

- Use direct-to-private-storage uploads with server-created object keys; never use raw filenames as paths.
- Enforce size both at upload issuance and completion; verify actual size, hash, magic bytes, and parser structure.
- Sanitize displayed filenames and metadata. Serve user files as attachments from a separate origin where practical.
- Scan files and quarantine until all required validation completes.
- Execute parsers/renderers/slicers in disposable, low-privilege containers/processes with resource controls, read-only base images, isolated scratch space, and no production credentials.
- Disable or constrain network access and external model-repair services.
- Reject uploaded G-code and pre-sliced printer artifacts. The trusted artifact must originate from the reviewed worker pipeline.
- Hash every artifact and bind the approved hash to the job authorization.

## API and web controls

- Validate all request/response schemas; reject unknown security-sensitive fields.
- Use parameterized ORM queries, bounded pagination, idempotency keys, optimistic concurrency, and state-machine preconditions.
- Configure strict CORS, CSP, HSTS, frame restrictions, MIME sniffing protection, referrer policy, and secure cookies.
- Escape untrusted content and avoid rendering uploaded HTML/SVG.
- Do not place secrets, tokens, signed URLs, private object keys, or personal data in client bundles, analytics, logs, or error pages.
- Return generic external errors with internal correlation IDs.

## Bridge and printer controls

- Use outbound TLS only and installation-scoped, rotatable credentials stored with Windows OS protection.
- Pair with expiring single-use codes and owner confirmation. Never ship a shared default bridge secret.
- Sign/bind commands to the installation, printer, job, artifact hash, nonce, and expiry.
- Require fresh heartbeat and explicit owner readiness. Refuse stale, duplicate, incompatible, or out-of-order commands.
- Persist command reconciliation state locally; after restart, query/report current printer state before accepting new work.
- Buyers cannot invoke pause/cancel/start endpoints. Buyer cancellation is a business request processed by the owner/system state machine.
- Provide an owner emergency stop/disconnect procedure outside dependence on the website.

## Audit and data integrity

Audit at least authentication security events, owner account changes, pricing versions, quote decisions/overrides, quote acceptance, payment claims and verification, refunds, queue changes, readiness acknowledgements, print commands/events, fulfillment changes, and sensitive data access.

Audit events are append-only to application roles and contain actor, action, target, time, request/correlation ID, before/after references, and reason where required. Avoid storing secrets or full model/payment evidence in events.

## Privacy, retention, and legal gates

The owner must approve a privacy notice, terms of service, model/IP declaration, prohibited-content policy, cancellation/refund rules, fulfillment responsibility, acceptable-use rules, and data-retention schedule before launch. Uploaded model retention must be configurable and deletion must cover derivatives and expired signed access.

Do not claim certifications, guaranteed dimensional tolerances, food/medical safety, IP clearance, or suitability for safety-critical use without written stakeholder and legal approval.

## Operational security

- Separate development, staging, and production accounts/secrets/data.
- Store secrets in deployment secret management; never commit `.env` values.
- Use least-privilege database/storage/queue/service identities and rotate credentials.
- Pin dependencies, scan lockfiles/images, review licenses, and patch critical vulnerabilities.
- Back up and test restore for the database and required objects.
- Alert on owner authentication anomalies, repeated cross-resource authorization failures, unusual upload/analysis load, bridge credential failures, and payment-reference abuse.

## Release security gate

- Authorization matrix and negative tests pass.
- Authentication, reset, verification, refresh rotation, logout, MFA, and revocation tests pass.
- Upload/parser/slicer resource and malicious-file tests pass.
- Manual payment cannot be self-verified or replayed.
- Queue and printer authorization resist duplicate/reordered requests and stale sessions.
- Secrets/configuration scan is clean; production debug endpoints and default credentials are absent.
- Backup restoration and bridge disconnect/manual fallback have been rehearsed.
- Owner-approved policies and operational runbook are published.
