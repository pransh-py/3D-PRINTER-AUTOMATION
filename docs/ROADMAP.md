# `xxx` One-Week MVP Roadmap

## Current priority override — October 19

Business work is deferred by the owner. The local `/print` station is implemented for
upload/configure/actual Orca slicing and single-send AD5X dispatch. The friend's printer has
ZMOD, so the primary adapter targets Moonraker G-code upload-and-print. Local software and
loopback protocol acceptance do not substitute for physical commissioning. Next: at the
printer, confirm network mode/versions, known-working profiles, actual plate and spool mapping;
then prove one supervised website-triggered print. See `VISIT_PREFLIGHT.md`.

The existing business milestones below are preserved for later, not current prerequisites.

## Delivery principle

Build verified vertical slices: each backend capability ships with the minimum buyer/owner UI and tests needed to exercise the real workflow. Defer visual polish and optional integrations until the ordering, payment, and printing state machine is reliable.

A production-quality public order system is achievable as a constrained MVP in one week only if stakeholder answers and hardware access arrive on time. Direct AD5X automation is the highest uncertainty and must retain a manual send fallback.

## Day 0: contract and access

- Confirm remaining pricing, materials, print presets, tax, fulfillment, Razorpay merchant/KYC ownership, test/live credentials, capture/settlement settings, manual-fallback beneficiary, legal policies, branding, and Windows/AD5X details.
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

Current status: private intake and validation are implemented. A pinned headless Orca adapter,
measured-output parsing, private derived artifacts/previews and owner slicing retry are now
implemented and locally tested with a labelled subprocess fixture. Actual Orca slicing and
repeatability still require owner-exported AD5X profiles and representative models.

## Day 3: pricing, quotation, and order snapshots

- Implement versioned materials, rates, profiles, pricing policy, and integer-money calculator.
- Create estimate breakdown and golden pricing tests from owner-approved cases.
- Build owner approve/override/reject flow with required reasons and quote expiration.
- Build buyer quote acceptance and immutable order snapshot.

Exit gate: stakeholder-approved sample cases match expected prices; historical accepted quotes do not change after rate updates.

Current status: versioned owner rate cards, recent-MFA activation, integer-paise calculation,
immutable analysis-linked estimate snapshots, owner administration UI, and buyer estimate display
are implemented. No policy is seeded or active by default. Real rates, GST treatment, approved
golden cases and actual AD5X metrics remain required for production acceptance. Owner issuance,
reasoned adjustment/rejection, buyer acceptance and accepted-order snapshots are implemented
with buyer/owner screens. See `LOCAL_WORKFLOW.md` for verified scope and remaining gates.

## Day 4: Razorpay Checkout and queue

Current status: disabled-by-default Checkout, callback/raw-webhook HMAC, exact current provider
correlation, interrupted-create receipt recovery and worker/API reconciliation are implemented.
PostgreSQL concurrency and fictional-provider HTTP tests passed. Real Test Mode/widget/webhook
delivery still need owner-configured credentials. Refunds and manual fallback remain unimplemented
pending approved policy/beneficiary procedure.

- Implement provider-neutral local payment intents and server-side Razorpay Order creation from accepted quote snapshots.
- Integrate Razorpay Standard Checkout in Test Mode and server-side checkout signature verification for immediate buyer feedback.
- Implement raw-body webhook signature validation, provider event/payment deduplication, out-of-order handling, amount/currency/order correlation and API reconciliation.
- Implement the transactional `PAID_CONFIRMED` transition, audit/outbox evidence, exactly-once print-job creation and queue UI.
- Implement owner payment-exception/refund operations and a disabled-by-default manual-UPI fallback with MFA-protected verification.

Exit gate: captured test payments enqueue exactly one job; callback-only, authorized, unsigned, replayed, unknown or mismatched events enqueue nothing; fallback claims cannot self-verify.

## Day 5: Windows bridge and AD5X spike

Current status: pairing, revocation, heartbeat, expiring manifest-bound download grants and a
Windows-compatible manual artifact client are implemented locally. Atomic printer-slot reservation,
fresh readiness and manual start records are implemented. No printer protocol or automatic
dispatch exists; real hardware, Windows service/protected credential storage and recovery remain pending.

- Build bridge pairing, protected credential storage, heartbeat, job lease, artifact download/hash verification, local state, and normalized events.
- Inspect actual Windows, Orca-Flashforge, AD5X firmware, LAN/WAN mode, and connectivity.
- Prove read-only status first, then safe send/start on disposable test models if supported.
- Implement owner readiness checklist, authorization nonce/expiry, idempotent start, reconciliation, and emergency disconnect.
- Document and test manual Orca-Flashforge send fallback.

Exit gate: a paid test job can be traced from queue to a safe physical test or the documented fallback; duplicate start attempts do not create duplicate prints.

## Day 6: fulfillment, UX, and hardening

Current status: manual printing/QA, fulfillment/tracking and disabled-by-default transactional
email are implemented. Notification retry/dead-letter diagnostics, real loopback SMTP,
PostgreSQL concurrency and database-only backup/restore passed. Courier integration, policy-driven
reprints/cancellation/refunds, restricted production DB roles, real service/hardware recovery and
production hardening remain pending. Public business/legal/support/portfolio copy remains a draft.

- Implement pickup/local-delivery/shipping status, manually approved charges/tracking, and buyer timeline.
- Complete service-led public pages and basic responsive visual system inspired directionally by the supplied reference without copying assets/content.
- Add email notifications, owner alerts, accessibility basics, empty/error/loading states, and support contacts.
- Run security, performance, backup/restore, failure recovery, and end-to-end suites.
- Conduct owner acceptance walkthrough and fix critical/high defects.

Exit gate: complete buyer and owner journeys pass in staging; restore and bridge/manual fallback work.

## Day 7: release

- Freeze changes except launch blockers.
- Re-run migrations, tests, dependency/security scans, configuration validation, and production smoke tests.
- Verify TLS, domain, sender, storage privacy, backups, retention jobs, alerts, owner MFA, Razorpay live webhook/capture/reconciliation settings, fallback controls, and policies.
- Train the owner on quotation, payment exceptions/refunds, fallback verification, printer readiness, failure/reprint, fulfillment, and incident handling.
- Launch with monitoring and a rollback plan.

Exit gate: owner signs off the runbook and acceptance checklist; no unresolved critical/high security or physical-safety issue remains.

## Verification strategy

- Unit tests: pricing, units, state transitions, authorization predicates, token/session rotation, file checks, and bridge protocol.
- Integration tests: database constraints, object storage, queue/outbox, email, Razorpay order/webhook/reconciliation, fallback verification, and migration upgrade/downgrade policy.
- Contract tests: OpenAPI/frontend clients and bridge/API messages.
- End-to-end tests: buyer registration through completion, owner rejection, payment success/failure/timeout, delayed webhook, cancellation/refund, print failure/retry, and offline bridge.
- Security tests: cross-buyer access, role escalation, CSRF, token replay, upload abuse, checkout tampering, invalid/replayed webhook, provider amount mismatch, fallback UTR replay, signed-URL expiry, duplicate start, and stale bridge.
- Hardware tests: representative single-color models, invalid artifacts, printer busy/offline, bridge restart, network loss, and duplicate command delivery.

## Launch blockers

- Pinned MinIO community image no longer pulls from Docker Hub/Quay; trusted-image or maintained S3-backend approval and real object-storage verification are outstanding.
- Unpatched high development-only `braces` advisory in the lint toolchain; runtime npm and installed Python scans are clean, but release review remains required.

- Missing pricing/material/profile inputs or no approved golden quote cases.
- No approved Razorpay merchant onboarding/KYC owner, test/live credentials, webhook endpoint/secret, capture/settlement/reconciliation procedure, or fallback beneficiary/procedure.
- No owner-approved terms/privacy/refund/prohibited-content policies.
- No working email sender/domain or owner MFA recovery.
- No hardware test access and no accepted manual print fallback.
- Any path that lets browser state, an unverified provider event or a buyer fallback claim mark payment confirmed, access another buyer's model, bypass queue authorization, or issue printer commands.

## Post-MVP order

1. Automated courier pricing, labels, tracking, and serviceability.
2. Inventory consumption and low-stock alerts.
3. More printers/operators with capability-aware scheduling.
4. Customer-approved model repair and richer 3D preview.
5. Multi-provider payment routing, saved methods or payment links if later justified.
6. Analytics, coupons, repeat-order tools, and visual refinement.
