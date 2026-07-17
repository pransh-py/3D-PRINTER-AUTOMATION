# `xxx` One-Week MVP Roadmap

## Delivery principle

Build verified vertical slices: each backend capability ships with the minimum buyer/owner UI and tests needed to exercise the real workflow. Defer visual polish and optional integrations until the ordering, payment, and printing state machine is reliable.

A production-quality public order system is achievable as a constrained MVP in one week only if stakeholder answers and hardware access arrive on time. Direct AD5X automation is the highest uncertainty and must retain a manual send fallback.

## Day 0: contract and access

- Confirm remaining pricing, materials, print presets, tax, fulfillment, UPI beneficiary, legal policies, branding, and Windows/AD5X details.
- Obtain safe development access to the Windows bridge computer and printer test window.
- Confirm domain/hosting/email choices and create non-production credentials.
- Freeze the MVP scope in `PRODUCT_REQUIREMENTS.md`.

Exit gate: no unresolved decision blocks auth/uploads; named owners and deadlines exist for pricing, payment, legal, and hardware inputs.

## Day 1: foundation and identity

- Scaffold web, API, worker, database, object storage, Redis, local development, migrations, lint, types, and tests.
- Implement configuration/secrets validation, structured logging, correlation IDs, health/readiness, and error envelopes.
- Implement buyer registration, verification, login, refresh rotation, logout, password reset, and profile.
- Provision owner account procedure, role checks, MFA foundation, and audit events.
- Add public shell and basic buyer/owner navigation.

Exit gate: identity integration tests and cross-role negative tests pass; no owner public signup exists.

Current status: the repository implementation and automated identity gate are complete. Live
production SMTP/Redis smoke testing and deployment owner enrollment remain release operations.

## Day 2: uploads and analysis

- Implement quote-request creation and signed private uploads.
- Validate supported formats, sizes, signatures, ownership, and quarantine state.
- Add bounded worker pipeline for metadata, build-volume checks, preview, and slicing.
- Persist versioned analysis results and expose buyer/owner result UI.
- Add failure/retry/timeout states and owner diagnostics.

Exit gate: approved sample models produce repeatable results; malicious/invalid/oversized samples fail closed; one buyer cannot access another's model.

Current status: private upload intake, transactional analysis enqueueing, fenced Redis Stream
delivery, bounded source validation, and buyer-safe analysis status UI are implemented. Real
Orca-Flashforge slicing, previews, and repeatability comparison remain blocked on owner-exported
AD5X machine/process/filament profiles and representative test models.

## Day 3: pricing, quotation, and order snapshots

- Implement versioned materials, rates, profiles, pricing policy, and integer-money calculator.
- Create estimate breakdown and golden pricing tests from owner-approved cases.
- Build owner approve/override/reject flow with required reasons and quote expiration.
- Build buyer quote acceptance and immutable order snapshot.

Exit gate: stakeholder-approved sample cases match expected prices; historical accepted quotes do not change after rate updates.

## Day 4: manual UPI and queue

- Implement versioned UPI beneficiary configuration and exact payment-intent display.
- Implement buyer UTR/evidence claim, duplicate detection, and owner verification with MFA/recent-authentication checks.
- Implement auditable paid transition, transactional outbox, print-job creation, and queue UI.
- Implement cancellation/refund-record placeholders and owner action dashboard.

Exit gate: no buyer/API manipulation can self-verify payment or enqueue an unpaid job; duplicate events remain single-effect.

## Day 5: Windows bridge and AD5X spike

- Build bridge pairing, protected credential storage, heartbeat, job lease, artifact download/hash verification, local state, and normalized events.
- Inspect actual Windows, Orca-Flashforge, AD5X firmware, LAN/WAN mode, and connectivity.
- Prove read-only status first, then safe send/start on disposable test models if supported.
- Implement owner readiness checklist, authorization nonce/expiry, idempotent start, reconciliation, and emergency disconnect.
- Document and test manual Orca-Flashforge send fallback.

Exit gate: a paid test job can be traced from queue to a safe physical test or the documented fallback; duplicate start attempts do not create duplicate prints.

## Day 6: fulfillment, UX, and hardening

- Implement pickup/local-delivery/shipping status, manually approved charges/tracking, and buyer timeline.
- Complete service-led public pages and basic responsive visual system inspired directionally by the supplied reference without copying assets/content.
- Add email notifications, owner alerts, accessibility basics, empty/error/loading states, and support contacts.
- Run security, performance, backup/restore, failure recovery, and end-to-end suites.
- Conduct owner acceptance walkthrough and fix critical/high defects.

Exit gate: complete buyer and owner journeys pass in staging; restore and bridge/manual fallback work.

## Day 7: release

- Freeze changes except launch blockers.
- Re-run migrations, tests, dependency/security scans, configuration validation, and production smoke tests.
- Verify TLS, domain, sender, storage privacy, backups, retention jobs, alerts, owner MFA, UPI display, and policies.
- Train the owner on quotation, payment verification, printer readiness, failure/reprint, fulfillment, and incident handling.
- Launch with monitoring and a rollback plan.

Exit gate: owner signs off the runbook and acceptance checklist; no unresolved critical/high security or physical-safety issue remains.

## Verification strategy

- Unit tests: pricing, units, state transitions, authorization predicates, token/session rotation, file checks, and bridge protocol.
- Integration tests: database constraints, object storage, queue/outbox, email, payment verification, and migration upgrade/downgrade policy.
- Contract tests: OpenAPI/frontend clients and bridge/API messages.
- End-to-end tests: buyer registration through completion, owner rejection, payment rejection, cancellation, print failure/retry, and offline bridge.
- Security tests: cross-buyer access, role escalation, CSRF, token replay, upload abuse, UTR replay, signed-URL expiry, duplicate start, and stale bridge.
- Hardware tests: representative single-color models, invalid artifacts, printer busy/offline, bridge restart, network loss, and duplicate command delivery.

## Launch blockers

- Missing pricing/material/profile inputs or no approved golden quote cases.
- No UPI beneficiary and verification procedure.
- No owner-approved terms/privacy/refund/prohibited-content policies.
- No working email sender/domain or owner MFA recovery.
- No hardware test access and no accepted manual print fallback.
- Any path that lets a buyer self-verify payment, access another buyer's model, bypass queue authorization, or issue printer commands.

## Post-MVP order

1. Razorpay Checkout and verified webhooks.
2. Automated courier pricing, labels, tracking, and serviceability.
3. Inventory consumption and low-stock alerts.
4. More printers/operators with capability-aware scheduling.
5. Customer-approved model repair and richer 3D preview.
6. Analytics, coupons, repeat-order tools, and visual refinement.
