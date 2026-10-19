# PrintFlow 3D Canonical Data-Flow Contract

- Contract version: 1.5
- Status: Authoritative DFD and information-flow contract
- Effective date: 19 October 2026
- Related schema: [`DATA_MODEL.md`](DATA_MODEL.md)

This document defines the external entities, numbered processes, data stores, directed flows and balancing rules used by the Level 0, Level 1 and Level 2 DFDs. APIs, workers, outbox consumers, the Windows bridge and documentation must preserve these trust boundaries.

The diagrams and detailed processes below describe the full production target. The current local
slice implements private intake, configured analysis, pricing/final quotations, accepted orders,
captured-evidence/outbox, disabled-by-default Razorpay/webhook/API and SMTP adapters, manual
production/QA and fulfilment. Local verification uses fictional E4 provider state and a loopback
E3 SMTP sink, never real payments or physical E6 commands. E5 receives only
installation-scoped, expiring artifact download grants. Connectivity and download receipts never
produce printer state or paid state. `LOCAL_WORKFLOW.md` and `DATA_MODEL.md` section 13 distinguish
the implemented projection from deferred stores/flows; sections 14–15 specify payment/mail
extensions. Existing diagrams remain target views; refunds/manual-UPI and direct dispatch are
not implemented, and API reconciliation does not fabricate webhook signature evidence.

Revision 1.5 adds a public, no-store print-preset catalogue derived from owner-reviewed files
and active material rates. Buyer selection enters D2 as a captured specification; analysis in
D3 must match its preset/hash/material before issuance into D4. Quotations and accepted orders
freeze those settings. Legacy orders have no manufactured selection data. For the explicitly
approved single-machine local setup, source bytes pass through authenticated, CSRF-protected
API PUT into a private local directory rather than browser S3 POST. The existing ownership,
expiry, byte-count, checksum, quarantine and worker-validation boundaries still apply.
Staging/production cannot use this local adapter. It creates no new E4 payment or E6 control flow.

## 1. External entities

| Code | External entity | Allowed interaction with the platform |
| --- | --- | --- |
| E1 | Buyer | Identity, private model intake, quote acceptance, Razorpay Checkout initiation and read-only order/fulfillment tracking for their own resources |
| E2 | Owner | Pricing/profile configuration, quote decisions, payment exception/refund and fallback decisions, queue/readiness control, QA and fulfillment |
| E3 | Email service | Receives notification requests and returns delivery outcomes; it has no business-state authority |
| E4 | Razorpay | Receives server-created Orders/API requests and Checkout payment details; returns API state and signed asynchronous payment/refund events |
| E5 | Windows print bridge | Makes outbound authenticated requests, claims one authorized job and reports printer/job events |
| E6 | FlashForge AD5X | Physical actuator reached only through the bridge or documented owner-operated manual fallback |

Razorpay is the primary payment provider. The platform trusts no browser payment result and no unsigned provider payload. A disabled-by-default manual-UPI fallback remains available only after owner issuance and independent real-account verification.

## 2. Data stores

| Code | Store | Canonical tables/objects |
| --- | --- | --- |
| D1 | Identity and access | `users`, `refresh_sessions`, `one_time_tokens`, `mfa_methods`, `mfa_recovery_codes`, `addresses` |
| D2 | Requests and private objects | `quote_requests`, `model_assets`, private source objects, previews, profiles and sliced artifacts |
| D3 | Analysis, profiles and pricing | `print_profiles`, `analysis_runs`, `analysis_asset_results`, `pricing_policies`, `material_rates`, `quote_estimates` |
| D4 | Quotes and orders | `quotes`, `quote_line_items`, `orders` |
| D5 | Payments and refunds | `payment_intents`, `payment_attempts`, `payment_provider_events`, `manual_upi_beneficiary_versions`, `manual_payment_claims`, `manual_payment_verifications`, `refunds` |
| D6 | Production | `printers`, `bridge_installations`, `bridge_heartbeats`, `print_jobs`, `print_job_items`, `print_readiness_checks`, `print_authorizations`, `print_job_events` |
| D7 | QA and fulfillment | `fulfillments` and immutable address/tracking snapshots |
| D8 | Audit, outbox and delivery | `audit_events`, `outbox_events`, `notifications` |

Private object storage is represented as part of D2/D3 because the database owns object identity, hash, trust state and retention state while bytes remain in private S3-compatible storage.

## 3. Level 0 context process

### Process 0 — PrintFlow 3D Platform

The whole platform accepts buyer/owner inputs, coordinates private analysis and commercial state, issues only owner-authorized production commands and returns safe status information.

| Source | Flow to Process 0 | Flow from Process 0 | Destination |
| --- | --- | --- | --- |
| Buyer | Registration, credentials, quote request, model metadata/bytes, quote acceptance, checkout request/result, optional fallback claim, cancellation request | Verification/session outcome, upload authorization, analysis/estimate/final quote, Razorpay checkout reference, payment/order/production/fulfillment status | Buyer |
| Owner | Profiles/rates, quotation decision, payment exception/refund/fallback decision, queue/readiness action, QA/fulfillment update | Action queues, model/price evidence, payment reconciliation/fallback evidence, queue/printer state, alerts and audit history | Owner |
| Email service | Delivery success/failure/provider ID | Verification/reset/status notification request | Email service |
| Razorpay | Signed webhook event, API payment/order/refund state | Server-created Order/refund/API request and Checkout handoff | Razorpay |
| Windows bridge | Heartbeat, claim, printer state, progress and terminal event | Job-bound authorization, signed artifact URL, manifest hash, nonce and command | Windows bridge |

## 4. Level 1 process decomposition

### 1.0 Identity and Access Control

- Inputs: registration, verification token, credentials, refresh token, owner MFA.
- Reads/writes: D1.
- Outputs: verified identity/session or generic failure; actor/session evidence to D8.
- Controls: no public owner signup, rate limiting, secure cookies, CSRF, rotation/revocation and recent-auth checks.

### 2.0 Quote Request and Model Intake

- Inputs: authenticated buyer request, selected owner-supported options, model upload metadata and completion.
- Reads/writes: D2; buyer/resource ownership from D1.
- Outputs: signed private upload authorization, validation status and immutable submitted request references.
- Controls: one to five files, 100 MB each, supported signatures/structures only, private server-created keys, no uploaded G-code or archives.

### 3.0 Model Analysis and System Estimate

- Inputs: submitted request version and private object references.
- Reads: D2 and active approved D3 profile/rates.
- Writes: D3 analysis/result/estimate evidence and D2 derived private artifacts.
- Outputs: printable/not-printable outcome, metrics, warnings, artifact hashes and immutable estimate evidence.
- Controls: isolated low-privilege worker, resource/time limits, no production secrets or printer/network access, idempotent fenced job.

### 4.0 Quote Review and Order Snapshot

- Inputs: estimate evidence, owner approval/override/rejection and buyer acceptance.
- Reads: D3.
- Writes: D4.
- Outputs: final time-limited quote, rejection reason or immutable accepted order snapshot.
- Controls: recent owner authentication for sensitive overrides; issued quote contents are immutable; acceptance is single-effect.

### 5.0 Razorpay Payment Confirmation and Fallback Review

- Inputs: accepted order, checkout completion identifiers, signed Razorpay events/API state, and optional owner-issued manual-fallback claim/decision.
- Reads/writes: D5 and D4; exchanges provider requests/events with E4.
- Outputs: checkout reference, processing/failed/confirmed state, exception/fallback review state and transactional print-job outbox event.
- Controls: server-created provider Order, no payment secrets in browser, raw-body HMAC verification, unique provider event/payment IDs, exact order/amount/currency correlation, captured/paid state, out-of-order reconciliation, idempotent confirmation and owner-only fallback verification.

### 6.0 Print Queue and Bridge Control

- Inputs: paid-verified outbox event, owner queue/readiness action, bridge heartbeat/claim/events.
- Reads/writes: D6; reads trusted artifacts from D2/D3.
- Outputs: queue state, job-bound authorization and normalized production events.
- Controls: only authorized next job, matching hashes, fresh bridge/printer state, owner readiness, expiring nonce and idempotent claim/start.

### 7.0 QA, Fulfillment and Buyer Tracking

- Inputs: print terminal status, owner QA outcome, pickup/delivery/shipping details.
- Reads/writes: D7 and D4; reads D6 events.
- Outputs: buyer-visible status timeline and fulfillment completion.
- Controls: fulfillment follows successful QA except an audited owner exception; address/tracking snapshot is immutable at dispatch.

### 8.0 Audit, Outbox and Notifications

- Inputs: actor/action/target/before/after event from every state-changing process and notification intents.
- Reads/writes: D8.
- Outputs: append-only audit history, at-least-once outbox delivery and email delivery state.
- Controls: no secrets/model contents/signed URLs in events; idempotency key on every outbox message.

## 5. Level 2 subprocesses

| Parent | Subprocess | Input | Output | Store |
| --- | --- | --- | --- | --- |
| 1.0 | 1.1 Register and verify email | Buyer profile/password | Pending/verified buyer, token/outbox | D1, D8 |
| 1.0 | 1.2 Sign in, MFA and authorize | Credentials/token/MFA | Session and authorization context | D1, D8 |
| 2.0 | 2.1 Create quote request | Buyer selections | Versioned draft request | D2 |
| 2.0 | 2.2 Issue private upload | File metadata/hash/size | Signed object authorization | D2 |
| 2.0 | 2.3 Validate and quarantine | Uploaded object | Trusted object reference or rejection | D2, D8 |
| 2.0 | 2.4 Submit request and enqueue | Validated request/object references | Immutable submitted version and analysis intent | D2, D8 |
| 3.0 | 3.1 Claim fenced job | Submitted request version and analysis intent | Exclusive bounded work lease | D3, D8 |
| 3.0 | 3.2 Verify file and extract geometry | Private source object | Format/hash/dimensions/warnings | D2, D3 |
| 3.0 | 3.3 Slice with approved profile | Validated geometry/profile | Filament/time/preview/sliced artifact/hash | D2, D3 |
| 3.0 | 3.4 Calculate estimate | Metrics + versioned rates | Immutable integer-paise estimate | D3 |
| 4.0 | 4.1 Owner review and decision | Estimate evidence | Approved inputs, override/rejection reason | D4, D8 |
| 4.0 | 4.2 Issue final quote | Approved components | Immutable line items and final quote | D4 |
| 4.0 | 4.3 Accept and create order snapshot | Valid quote + buyer acceptance | Single immutable order | D4, D8 |
| 5.0 | 5.1 Create local intent and Razorpay Order | Accepted order snapshot | Exact provider Order and checkout reference | D4, D5, E4 |
| 5.0 | 5.2 Verify callback for buyer feedback | Stored provider Order + callback identifiers/signature | Processing/invalid immediate result; no queue effect | D5, D8 |
| 5.0 | 5.3 Validate and deduplicate webhook | Raw body + signature + event ID | Immutable valid/rejected provider event | D5, D8, E4 |
| 5.0 | 5.4 Correlate and reconcile provider state | Event/API state + local intent/order | Captured, failed or exception outcome | D4, D5, E4 |
| 5.0 | 5.5 Commit confirmed transition | Correlated captured evidence | `PAID_CONFIRMED` order + one print-job outbox event | D4, D5, D8 |
| 5.0 | 5.6 Review owner-issued fallback | UTR/evidence + observed bank facts + recent MFA | Immutable confirmed/rejected fallback decision | D4, D5, D8 |
| 6.0 | 6.1 Create/order print queue | Paid outbox event | Job and item manifest | D6 |
| 6.0 | 6.2 Check readiness and authorize | Eligible job + owner checklist + fresh health | Expiring job/printer/bridge-bound authorization | D6, D8 |
| 6.0 | 6.3 Bridge claims and executes | Heartbeat/claim + authorization | Hash-verified send/start or structured refusal | D6 |
| 6.0 | 6.4 Reconcile job events | Progress/terminal/restart state | Idempotent normalized job state | D6, D8 |
| 7.0 | 7.1 Record QA result | Completed print + owner inspection | QA pass/fail/reprint decision | D6, D7, D8 |
| 7.0 | 7.2 Arrange fulfillment | QA pass + owner details | Pickup/delivery/shipping snapshot | D7, D8 |
| 7.0 | 7.3 Publish buyer timeline | Order/job/fulfillment events | Buyer-safe current/history view | D4, D6, D7 |
| 8.0 | 8.1 Append audit event | State-changing action evidence | Immutable audit row | D8 |
| 8.0 | 8.2 Deliver notification | Outbox notification intent | Provider request/result | D8, Email service |

## 6. DFD balancing matrix

Level 0 and Level 1 are balanced when every context flow appears in the decomposition without creating a new external authority.

| Level 0 flow family | Level 1 realization |
| --- | --- |
| Buyer identity inputs/results | Process 1.0 |
| Buyer request/model inputs and upload/status outputs | Process 2.0 |
| Analysis and estimate outputs | Process 3.0, delivered through 4.0 |
| Quote issue/acceptance and order state | Process 4.0 |
| Checkout/fallback instruction, buyer result and payment status | Process 5.0 |
| Production/fulfillment tracking | Processes 6.0 and 7.0 |
| Owner profiles/rates and evidence | Process 3.0 |
| Owner quote decision | Process 4.0 |
| Owner payment exception/refund/fallback decision | Process 5.0 |
| Razorpay Order/API request and signed provider event | Process 5.0 |
| Owner queue/readiness and printer state | Process 6.0 |
| Owner QA/fulfillment | Process 7.0 |
| Email request/delivery outcome | Process 8.0 |
| Bridge authorization and event exchange | Process 6.0 |

Level 1 and Level 2 are balanced because every Level 1 process is decomposed into the numbered Level 2 subprocesses in Section 5, using the same inputs, outputs and stores.

## 7. Information classification

| Classification | Examples | Flow/storage rule |
| --- | --- | --- |
| Public | Service pages, supported formats, general process | May be cached publicly after review |
| Buyer-private | Identity, address, quote/order data | Authenticated owner/buyer-resource access only |
| Model-private | Source models, previews, sliced artifacts | Private object storage, short-lived signed URLs, access logged |
| Payment-sensitive | Provider order/payment/event IDs, normalized method type, fallback UTR/evidence, refund and reconciliation decisions | Owner/buyer scoped; secrets/signatures/full payloads never logged; fallback evidence scanned and retained by policy |
| Secret | Password/MFA/bridge credentials, session tokens | Hashed or encrypted; never returned/logged |
| Safety-critical | Readiness checks, authorizations, job events | Owner/bridge only, short-lived, hash-bound, append-only evidence |

## 8. Prohibited flows

- Buyer or browser callback directly to payment-confirmed state.
- Buyer to queue mutation, readiness, print authorization or printer command.
- Public browser to private object-store administration.
- API request handler to CPU-heavy parsing or slicing.
- Analysis worker to production secrets or the printer network.
- Internet-originated inbound connection to the Windows bridge.
- Bridge command without job, artifact hash, printer, bridge, nonce and expiry binding.
- Unsigned, uncorrelated, authorized-only or mismatched provider event directly to `paid_confirmed`.
- Payment screenshot/UTR directly to `paid_confirmed`.
- Client-side status directly to a server business transition.
- Logs/analytics containing secrets, signed URLs, private model contents or full payment evidence.

## 9. Failure and recovery flows

- Failed uploads remain rejected/quarantined and never enter analysis.
- Timed-out analysis releases its fenced lease and retries within bounded policy.
- Outbox publication is at-least-once; consumers deduplicate by idempotency key.
- Delayed, duplicate or out-of-order payment events reconcile idempotently; invalid signatures and amount/order mismatches fail closed and alert the owner.
- Razorpay API/webhook outage leaves the order unpaid or processing; it never bypasses confirmation. The owner may explicitly issue the manual fallback.
- Offline/stale bridge causes a structured refusal; the owner may use the documented manual Orca-Flashforge fallback.
- After restart, the bridge reports observed printer/job state before claiming new work.
- Reconciliation commands are idempotent and append audit evidence.
- Failed fulfillment/notification records remain visible for owner action and bounded retry.
