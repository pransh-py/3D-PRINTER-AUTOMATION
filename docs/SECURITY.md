# `xxx` Security and Safety Baseline

## Security objectives

1. A buyer can access only their own identity, models, quotations, payments, orders, and fulfillment data.
2. Only the owner can approve prices, manage payment exceptions/refunds, verify manual fallbacks, manage queues, or authorize physical printer actions.
3. Untrusted model files cannot execute code, reach secrets, access other files, or control the printer.
4. Browser state, an unsigned provider message, or a manual claim cannot become a paid order without independent server-side verification.
5. Retries, duplicate requests, stale pages, or network recovery cannot start duplicate prints or duplicate business transitions.
6. Security-relevant actions remain attributable and recoverable.

## Threat boundaries

- Public browser and API traffic is hostile by default.
- Uploaded models, metadata, filenames, archives, previews, and slicer output are untrusted.
- Razorpay callbacks and webhooks cross an external trust boundary; their IDs, signatures, amount, currency, order binding and state are untrusted until verified server-side.
- Buyer-submitted UTRs and screenshots for the manual fallback are unverified claims.
- The Windows bridge may be offline, stale, compromised, or connected to unexpected firmware.
- The printer is a physical actuator; logical authorization does not prove the bed/material/nozzle is safe.
- Owner credentials are high-value because there is one operational account.

## Authentication and authorization

- Normalize and verify email ownership; prevent enumeration in registration/reset responses.
- Hash passwords with Argon2id; apply breached/common-password checks without sending passwords to third parties.
- Rate-limit login, registration, verification, reset, MFA, upload creation, quote acceptance, checkout creation, payment reconciliation and fallback claims by layered identifiers.
- Use short access-token lifetimes, rotated refresh sessions, secure HTTP-only cookies, CSRF protection, and server-side revocation.
- Require MFA and recent authentication for owner payment exceptions, refunds, fallback verification, price overrides, printer actions, UPI-beneficiary changes, exports, and credential changes.
- Enforce role and resource ownership in domain/service code and database queries, not only routes or UI.
- Deny by default. Keep an authorization test matrix covering both roles and cross-buyer access attempts.

## Razorpay payment controls

- Create Razorpay Orders only on the server from immutable accepted-order amount and currency. Never accept those fields as browser authority.
- Keep Razorpay Key Secret and webhook secret in deployment secret management. Only the public Key ID may reach the browser.
- Never mark paid from checkout JavaScript, a redirect/callback alone, `payment.authorized`, a screenshot, a UTR shape, a QR scan, or a buyer request.
- Verify checkout signatures server-side using the locally stored Razorpay Order ID. Verify webhook HMAC over the exact raw request body before parsing trusted fields.
- Deduplicate the provider event ID and provider payment ID. Assume webhooks may be duplicated, delayed or delivered out of order.
- Require exact local/provider order binding, INR currency, amount and captured/paid state. Fetch provider state when reconciliation is required.
- Use a single idempotent domain transition so captured evidence, retries and manual reconciliation can create no more than one paid/queue effect.
- Restrict refund initiation and exception resolution to the owner with recent MFA; reconcile provider refund events without rewriting original payment evidence.
- Allow only the checkout/provider origins needed by the current Razorpay integration in CSP and connect policies. Review the allowlist when Checkout changes.

## Manual UPI fallback controls

- Keep the fallback disabled unless the owner explicitly issues it for an order.
- Owner verification must compare beneficiary, amount, reference, and received/settled state in the actual account.
- Unique constraints and audit alerts detect duplicate UTR/reference submissions; owner adjudication remains necessary.
- UPI beneficiary changes require owner MFA, show a confirmation summary, create a new version, and never alter existing payment intents.
- Do not expose full bank details beyond what is required for payment.
- Payment evidence is private, access-logged, malware-scanned, and deleted according to the retention policy.

## Upload and slicing controls

The owner-approved local-folder backend is development/test-only and loopback-only. Its uploads
are authenticated, CSRF-protected streams tied to private buyer-owned intents, with exact size/hash
checks. Server keys are hashed into opaque directory names, not interpreted as paths. No public
file-serving route exists. Use a private filesystem directory, keep configuration/access files out
of screenshots and Git, and retain the S3 requirement for staging/production. Real local storage
and Orca acceptance do not verify the production network/memory sandbox or backup/restore.

Implemented local controls and unverified production gates are separated in `LOCAL_WORKFLOW.md`.
The new bridge is download-only: no physical command is inferred from connectivity, download or
acknowledgement. Callback/raw-webhook HMAC and provider correlation have local adversarial tests,
not a real merchant integration test. Windows credential persistence, container memory isolation,
restricted production database roles and hardware reconciliation remain release requirements.

Workflow email is disabled by default. Its outbox contains recipient IDs/template codes only;
delivery stores a purpose-separated keyed destination digest and checks active, verified role
and unchanged destination. SMTP errors are safe codes. Owner diagnostics/retries enforce role,
recent MFA and CSRF. Mail never authorizes payment/printing; SMTP acceptance is not inbox delivery.

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

Audit at least authentication security events, owner account changes, pricing versions, quote decisions/overrides, quote acceptance, Razorpay order creation, validated/rejected provider events, paid transitions, reconciliation/refunds, fallback claims/verification, queue changes, readiness acknowledgements, print commands/events, fulfillment changes, and sensitive data access.

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
- Alert on owner authentication anomalies, repeated cross-resource authorization failures, unusual upload/analysis load, bridge credential failures, invalid webhook signatures, provider/local amount mismatches, reconciliation delays, repeated checkout failures and fallback-reference abuse.

## Release security gate

October 11 local scan: runtime npm and installed Python dependency scans are clean after the
documented upgrades. The development-only `braces` lint dependency has an unresolved high
advisory with no published patch; this is not suppressed or treated as launch approval.
The pinned MinIO image is unavailable from both official registries, and its community source
is archived. Storage replacement/trusted-image selection, real private-object acceptance and
object restore are outstanding. See `LOCAL_WORKFLOW.md` for raw reports, versions and scope.

- Authorization matrix and negative tests pass.
- Authentication, reset, verification, refresh rotation, logout, MFA, and revocation tests pass.
- Upload/parser/slicer resource and malicious-file tests pass.
- Checkout callbacks cannot self-confirm payment; webhook signature, amount/currency/order correlation, event deduplication and reconciliation tests pass.
- Manual fallback payment cannot be self-verified or replayed.
- Queue and printer authorization resist duplicate/reordered requests and stale sessions.
- Secrets/configuration scan is clean; production debug endpoints and default credentials are absent.
- Backup restoration and bridge disconnect/manual fallback have been rehearsed.
- Owner-approved policies and operational runbook are published.

## Local print station boundary (October 19)

The new printer station is a trusted **single-machine operator tool**, not a public upload
service. Web and API bind loopback by default. The owner's explicit `run --lan-host`
option additionally permits one RFC 1918 IPv4 web address on the configured web port;
the API remains loopback-only behind the web proxy. Devices allowed onto that LAN can
access the operator station and its print controls. Restrict firewall access to the
trusted local network; no internet port forwarding is configured. The printer rewrite
exists only when explicitly launched in station mode. Mutations require an exact
configured UI Origin and a random
per-process token; Host checks reject DNS rebinding. There is no permissive CORS. HTTP clients
can select only options, never printer hosts, credentials, filesystem paths or arbitrary commands.

Models/configuration/artifacts stay in ignored private local directories; credentials are
entered with hidden terminal input and stored mode 0600. No secrets are sent to the browser.
Validation and slicing use credential-free subprocesses and bounded inputs/outputs/timeouts;
the local process mode is **not a complete OS sandbox for hostile internet uploads**. Do not
publish this station or repurpose it as a SaaS endpoint. Physical control stays disabled until
profiles, build plate, ZMOD behaviour and spool matching are commissioned. Neither safety
interlocks nor printer/network authentication are disabled automatically.

Submission idempotency, one-active-job persistence and intent-before-send protect against
duplicate starts inside this station, not independent third-party printer clients. An ambiguous
send is never retried; check the printer and its pending queue before acknowledgment. A laptop
shutdown cannot guarantee a printer stops a job it already received. Use physical controls.

For Moonraker printers, `native-status` privately pairs the native API using read-only
`/detail` validation. Starts require this pair: Moonraker only uploads with `print=false`,
then a narrow native `/printGcode` request binds the generated filename and verified T0
slot/material/colour. Browser input cannot choose the endpoint or supply arbitrary commands.
Pairing credentials stay in the existing 0600 configuration and never enter status
responses or slicer subprocesses. Automatic stop
detection requires consistent native and Moonraker idle evidence; missing connections,
heating, paused/busy states or queued work never count as proof of a stopped attempt.
The monitor only updates local job status and never issues stop, reset or retry commands.

## Commerce dispatch boundary — October 21, 2026

`printer_dispatch_enabled` defaults to false. Buyer cookies never authorize bridge pairing,
printer dispatch or production writes. Dispatch writes require the existing primary-owner role,
recent enrolled MFA, trusted Origin and session CSRF. The server also requires an exact captured
payment, a reserved ready job, an unchanged approved manifest, one file/copy, a fresh bridge and
fresh physical readiness. Claiming does not extend the ten-minute readiness deadline: it is
checked again before acknowledging a send.

Bridge credentials are random, stored hashed by the API, scoped to the paired adapter and
revocable. The connector's separate local file is mode 0600; pairing input is hidden and no
credential is printed. Requests allow HTTPS or explicit loopback HTTP and never follow redirects.
Manual adapters cannot use dispatch routes, and station adapters cannot use manual bridge
handoff routes. A heartbeat proves connectivity only, not a clear bed or idle printer.

The connector accepts only an explicitly approved commerce profile hash/material with the same
commissioned plate type. G-code must declare that plate, material and the mapped colour; missing,
ambiguous or changed metadata refuses the send. There is no relabelling of G-code or rewriting
of motion/temperature commands. The unchanged single-tool ZMOD preprocessor adds its existing
metadata/checksum wrapper. Existing driver checks still run immediately before execution.

Authorization, artifact and station-event bindings prevent another bridge, stale/changed files
or mismatched filenames/hashes from advancing the order. Event IDs replay only identical content.
Unexpected transitions, completion without a prior send and events after an owner closes the
attempt are rejected. The local journal persists exact telemetry bodies until acknowledged;
rejected telemetry is retained for review, never used to retry a physical action.

Cancelling an expired or revoked unclaimed authorization returns the job to preparation and
requires fresh readiness. This safe reset remains available with dispatch disabled and cannot
create a new authorization. Its conditional update refuses a grant already claimed/consumed;
the same lock order and CAS fence ensure a racing claim and reset cannot both succeed.
Refusal retains the reservation for owner review. An uncertain send requires local inspection;
recording a failure in the dashboard does not stop a printer. The native station lock and
one-active-job journal index prevent simultaneous native and commerce physical controllers.
Physical commissioning of this new adapter remains a separate supervised acceptance step.

## Buyer phone identity through OTPigeon — October 21, 2026

The owner selected WhatsApp OTP (not carrier SMS) for buyer signup and login. A successful
code proves control of that WhatsApp number, not legal identity. Indian mobile numbers are
canonicalised to +91 E.164. Phone-only accounts have no fabricated email address or password;
their unique verified phone identifies the buyer. Existing email accounts remain separate and
can still sign in with email/password. No automatic account linking or owner phone login exists.
Owner password/TOTP, verified-payment decisions and physical-printer authorization are unchanged.

PrintFlow owns five-minute, one-use challenges, HMAC code digests, five-guess budgets, bounded
request/verification rates and a sixty-second resend cooldown. Codes, challenge handles, phone
numbers and sender credentials must never enter logs or audit details. No account/session is
created until a delivered challenge is correctly verified. Failed delivery cannot claim success.
Only the hardened OTPigeon Node delivery path is reused; its unauthenticated POC verification,
MongoDB and multi-sender/QR HTTP APIs are not exposed. Sender credentials and LocalAuth state
are private local files, separate from the browser and printer station. QR pairing is performed
by the owner in their interactive terminal, never captured or posted in chat.

This unofficial WhatsApp Web sender is local-development/demo only; production configuration
must refuse it. Real delivery remains unverified until the owner pairs a sending account and
personally requests a code to their own phone. Sender acceptance is not a delivery receipt.
WhatsApp order notifications are not part of this change: phone-only buyers follow order status
in their dashboard, and verified-email eligibility remains mandatory for email notifications.

The cookie-isolated phone preview also exposed an existing local-storage validation defect:
Pydantic returns IPv6 loopback's host as `[::1]`, but the allowlist contained only `::1`.
`config.py` now accepts that exact bracketed loopback spelling; public hosts and non-loopback
IPv6 remain rejected. `test_phone_auth.py` covers all three cases. The genuine fresh-process
Settings probe and before/after pictures are ignored under
`.local/evidence/otpigeon-identity/{before,after}/ipv6-*`; they exercise configuration validation,
not a mock result, and contact neither a database nor WhatsApp nor a printer.

Local verification on October 21 recorded 314 passing API/worker tests (two opt-in real-Orca
checks skipped), 66 passing web tests, four passing sender tests, Python type/lint checks,
web type checking and an isolated optimized web build. File-backed SQLite exercises concurrent
issuance, single-use redemption and the five-guess limit; PostgreSQL concurrency and real
WhatsApp delivery have not been exercised. Browser inspection covers the actual unavailable
sender response, preserved owner password/TOTP routing and a 375px signup layout with no
horizontal overflow. The verification sender refuses every send and is not a production fallback.
Evidence is ignored under `.local/evidence/otpigeon-identity`; sender dependency limitations
and the owner's private pairing procedure are documented in `services/whatsapp-otp-sender/README.md`.
The original demo and printer runtime remain untouched. The separate phone preview uses its own
database, Redis job namespace and IPv6-loopback cookie host; its build/source fingerprint is
recorded before browser capture. Real delivery requires replacing the verification-only refusing
transport with the configured adapter, followed by owner-controlled pairing and first-code entry.
