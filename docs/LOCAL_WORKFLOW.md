# Local order workflow and verification

The project has private intake, configured analysis, immutable quotations/orders, disabled-by-default Razorpay Checkout/webhook/reconciliation code, transactional status email, manual Windows handoff, QA and fulfilment tracking. These are locally tested capabilities, not a completed production product or launch approval. Business rates/policies, real gateway credentials and hardware access remain unavailable.

## Real-component local workflow — 19 October 2026

The owner approved a private filesystem backend for today's loopback-only setup and confirmed
the FlashForge AD5X. Robu.in is the ordering reference, not a separate automation tool. One
read-only Claude Opus 5.5/high initial analysis was completed and its exact model verified;
all implementation and final checking stayed with Codex, as requested. No later model review,
commit, push, deployment, live payment or printer command was performed.

`tools/local_service.py` starts dedicated PostgreSQL/Redis/Mailpit containers and the actual API,
worker and web, with private mode-0600 configuration and no seeded business records. It provides
init, migration, interactive owner provisioning, reviewed-profile configuration and non-secret
readiness commands. See the README for the shortest startup sequence. Local files are never
publicly served; upload PUTs enforce session/CSRF/origin, buyer ownership, intent expiry, exact
length and checksum. Production/staging cannot select this adapter. The unavailable MinIO image
still blocks the older S3 setup, not this approved local alternative.

The request page now collects an offered material, a complete quality/infill preset, available
colour when configured, quantity, fulfilment and notes. It previews actual STL/OBJ geometry in
the browser, preserving dimensions and orientation. Only priced, hash-pinned profile combinations
are offered. Their nozzle/layer/infill/support/wall settings follow the request, worker analysis,
final quotation and accepted-order snapshot. The worker calculates the first estimate automatically
from measured slicing and an active rate card; a persisted-state pass recovers a slice/calculation
crash gap without impersonating the owner or replacing human decisions. The browser polls active
analysis and shows success or failure without a manual reload.

### Actual acceptance evidence

A separate PostgreSQL database, `printflow_acceptance_751cc12995`, private objects and Redis DB 1
were used for real-component acceptance. It is not the clean service's business database. Fictional
owner/buyer accounts and clearly labelled verification rates were created through normal owner
provisioning, password/MFA, rate-card activation, buyer registration, actual local SMTP verification
and browser login. No analysis result, captured payment or production job was seeded.

Official OrcaSlicer 2.4.2 for macOS was downloaded from the vendor's GitHub release; its DMG SHA-256
matched the release asset digest:
`e15e7bb1b66214ec6e96b169b388004179c4f5f705effcdaf8c80d4992ee0366`.
Vendor AD5X 0.4 mm machine, 0.20 mm Standard process and PLA Basic filament profiles were resolved
with inherited settings intact, then hash-pinned. These are **verification profiles**, not a claim
of calibration or approval for the friend's physical printer.

The real browser uploaded a closed 10 mm cube. The worker extracted 710 mg filament and 345 seconds
from real Orca output, stored the derived private artifact and automatically calculated an estimate
from the explicit verification rate card. The owner issued a quotation through the MFA-authenticated
workspace; the buyer accepted through the UI. The immutable order remains payment pending, with
zero captured payments and zero production jobs. Desktop and 390 px buyer inspection were performed.
No sliced PNG was emitted by this profile; the interactive browser geometry preview is a separate
feature, not a fabricated slicer thumbnail.

A second, closed binary STL (10,935,084 bytes, 218,700 triangles) also passed the real Next.js proxy,
private storage, validation, Orca slicing and automatic estimation. Status changed in the browser
without a reload. An earlier 11 MiB whitespace-padded ASCII fixture passed transport but was rejected
by Orca (`slicer_failed`); it correctly received no estimate or order. This is not reported as a
successful slice, and neither large-file check proves the full 100 MiB limit on every deployment.

The owner can now inspect actual validated STL/OBJ geometry or download a validated source for
other formats. `/owner/quote-requests/{request_id}/models/{asset_id}` is owner-only, rate-limited,
private/no-store and attachment-only; it checks request binding, validation status and SHA-256
before serving any bytes. Quarantined/rejected sources are not downloadable. Migration
`0012_model_review_audit` records non-secret model-access events. The normal HTTP regression covers
buyer denial, quarantine refusal, valid owner download and a mismatched request. Real owner browser
inspection loaded the dense cube from private storage, with no console errors.

Ignored, real UI pictures are under `.local/printflow_acceptance_751cc12995/`:
`real-model-preview-desktop.png`, `owner-approved-real-slice.png` and
`buyer-accepted-real-order-mobile.png` and `owner-private-model-review.png`. The private `access.json` and `runtime.json` are never
delivery artifacts. Earlier browser-lab screenshots remain explicitly fictional historical evidence.

### Redis idle failure: genuine before and after

Starting the real worker exposed an uncaught Redis `TimeoutError` on an empty queue: the default
one-second socket timeout equalled the intentional one-second XREADGROUP block. Unit queue doubles
had not reproduced that network timing. `.local/evidence/worker-idle/probe.py` reproduced the actual
empty-stream read in its own disposable Redis stream before repair (failure after 1.005 seconds).
`services/worker/src/xxx_worker/main.py` now uses a worker socket deadline at least two seconds longer
than its queue block, leaving the short API/connection timeout unchanged. Replaying the same trigger
returned normally with no message after 1.054 seconds; a regression checks the timeout relationship.
The worker then stayed alive during the real upload/slicing flow.

Genuine before/after screenshots and underlying observations are
`.local/evidence/worker-idle/before.png` / `before.json` and `after.png` / `after.json`.
The pair was posted in the current chat; it demonstrates the actual symptom/replay, not a passing
test screenshot. Factory-based local storage also updated the existing shutdown harness's storage
hook; shutdown, migration-targeting and forward-only migration regressions pass.

The consolidated Python suite passed **159 tests**; web passed **41**. Ruff, mypy (70 source files),
TypeScript and optimized Next.js build passed. ESLint has no errors and the pre-existing account
sign-out navigation warning. Generated `.next-verification` output is ignored by Git and ESLint,
allowing independent development and optimized acceptance frontends. The runtime npm audit has
no reported advisories; development dependency advisories and production isolation remain gates.

Physical dispatch remains disabled. Follow `VISIT_PREFLIGHT.md` to review real profiles and a
station-export comparison, configure genuine Razorpay **test** credentials, pair a reachable Windows
bridge securely, and perform an owner-supervised print. Missing business policies, credentials and
hardware observations are not replaced with fabricated evidence.

The checked source/configuration fingerprint is
`d482ef01125734029dd4985c206da2b9a6a23ae3621ba44d3a0eb493b4ce03dd`:
sorted unique `git ls-files -co --exclude-standard` paths for web source/config/package files,
API source/tests/migrations, worker source/tests, bridge, the three new local/preset/comparison
tools and Compose; hash each file with SHA-256, then hash that list. Documentation, ignored runtime
secrets/data and screenshots are excluded. The sanitized database observations are
`.local/printflow_acceptance_751cc12995/actual-acceptance-observations.json`.

## What works locally

Buyers select a quantity and pickup, local delivery or shipping when creating a request. Source files remain private and quarantined until validation. A configured analysis worker can run a pinned Orca executable with three owner-reviewed, standalone profiles, extract measured filament mass and normal-mode duration, and store hash-bound G-code and an optional PNG preview. Without profiles, validation stops at `awaiting_profile`; it never substitutes guessed slicing metrics. The owner can retry a waiting-profile or slicer-failed request after configuration. Invalid source geometry cannot be re-enabled through that retry.

The pricing calculator uses measured units multiplied by the number of copies, with the existing per-order setup/minimum/contingency/tax calculation. No production policy is seeded. The owner issues a final quotation from a current estimate, or rejects the request with a reason. Adjustments require a reason. Reissuing supersedes the old quotation; accepted quotations cannot be replaced. An expired estimate can be refreshed from the same approved analysis and current rate card. Refresh supersedes unaccepted issued quotations and shares the request-version comparison with acceptance; only one concurrent operation wins. Issued commercial values and accepted order snapshots are protected against ORM edits. This application-level protection does not replace restricted PostgreSQL roles or a production database audit.

Acceptance creates one buyer-owned order and freezes the exact line items, amount, pricing/profile references, quantity, fulfilment choice and artifact hashes. Shipping and delivery require an address snapshot; acceptance retries cannot change it. The accepted destination is visible only to the owner and that order's buyer. Buyer responses exclude private object keys and operator notes.

Checkout is disabled by default but implemented. The API records one intent before creating an exact-amount provider Order. An uncertain create is never automatically repeated: authenticated receipt search must find exactly one match or the owner investigates. The browser loads Standard Checkout on demand; its HMAC-verified callback records feedback only. Raw-body signed webhooks and authenticated API observations additionally require the current exact INR paid order and a captured, unrefunded matching payment. The capture transaction commits evidence, paid state, audit, production outbox and notification intents together. Retries/out-of-order messages cannot duplicate queue effects. Worker, buyer and recent-MFA owner reconciliation share these checks. No public endpoint can mark an order paid. Real Razorpay/widget/webhook delivery is unverified; refunds and manual-UPI fallback remain unimplemented.

Workflow email is disabled by default and independent of identity verification/reset email. The worker publishes private delivery records from transactional outbox events and sends generic status/sign-in notices via SMTP. Active verified recipient role and a keyed destination digest are checked; changed addresses fail closed. Fenced leases, bounded backoff and owner-visible dead letters support recovery. Owner retry requires recent MFA and is audited. Mail never authorizes business state. SMTP acceptance is not inbox delivery; a crash after acceptance can duplicate email.

The worker drains the production outbox into a FIFO queue. Duplicate delivery has one business effect. Recent owner MFA is required for changes. Preparing a job atomically reserves the single logical AD5X slot. A fresh checklist binds the reviewed artifact manifest to physical readiness; only the owner can record a manual start. Completing a print moves it to QA, not directly to delivery. QA failure records an operator reason and stops fulfilment. A successful QA decision permits pickup readiness, local delivery or shipment; shipping requires carrier and tracking text. Completion records actual collection or delivery. Automated courier serviceability and tracking integrations are not implemented.

## Windows handoff and safety

`services/bridge/bridge.py` is a standard-library, Windows-compatible manual handoff client. It makes outbound requests, refuses non-HTTPS origins except loopback, disables redirects, validates the authorized manifest and each artifact hash, and never overwrites an existing handoff directory. It contains no AD5X protocol, heater, movement, send, start or stop command. A bridge heartbeat proves connectivity only; the printer remains `unknown` until a real adapter and hardware observations exist.

Use the Bridge tab in `/operations` to create a one-use pairing token. Pairing expires after five minutes and replacing it invalidates the previous credential. Run this on the print station:

```sh
python services/bridge/bridge.py --api https://YOUR_API_ORIGIN --pair
```

Enter the token at the terminal prompt. The credential is shown once; store it in Windows Credential Manager. The prototype intentionally does not persist a plaintext credential. Automatic Windows-protected credential storage, unattended service installation and restart reconciliation remain production work.

To heartbeat and list pending handoffs, run the same command without `--pair`. After preparing a job and completing the five-item checklist, the owner can authorize a two-minute download grant. A bridge must have heartbeated within 60 seconds. Use `--receive AUTHORIZATION_UUID` to download into a fresh directory. Verify all quantities and review the files in Orca before any manual printing. Download acknowledgement does not mean a print started. The owner separately records manual start, print finish and QA in the website. Revocation, expiry, a changed manifest or a job leaving readiness blocks artifact access.

Physical testing, the actual AD5X/Orca-Flashforge setup, Windows credential protection and owner operating procedures remain launch gates. Never test these controls against an occupied printer or treat the lab artifact as printable.

## Approved slicer setup

Configure the commented settings in `services/api/.env.example` only after reviewing the executable and exported `machine.json`, `process.json` and `filament.json`. The executable hash is SHA-256 over its exact bytes. The profile hash is SHA-256 over each filename, a NUL byte and its exact file bytes, in that order. Export standalone profiles; inherited preset dependencies are not resolved by this adapter. Version is an owner-verified build label bound to the configured executable hash, not a guessed detected version.

The worker scrubs application credentials, imposes a wall-clock timeout, CPU/file-size/open-file limits, rejects missing measured metrics and refuses multiple output plates. Production uses the network-isolated bubblewrap namespace and needs a separately tested container memory limit and runtime mounts. Bubblewrap was not exercised on this Mac. The earlier subprocess tests use an explicitly labelled fixture executable; the real Orca run is documented above. Neither result proves physical printer compatibility or calibrated print quality.

## Isolated browser lab

Run the test-only fixture on loopback:

```sh
.venv313/bin/uvicorn workflow_lab:create_lab --factory --app-dir services/api/tests --host 127.0.0.1 --port 8011
API_INTERNAL_URL=http://127.0.0.1:8011 npm --prefix apps/web run dev -- --hostname 127.0.0.1 --port 3100
```

The lab creates a new ignored `.local/workflow/browser-*` SQLite database every run. Its owner/buyer credentials and TOTP secret are written to a mode-0600 access file named in terminal output. Use normal sign-in and owner MFA; no auth dependency is bypassed. The lab substitutes storage and the rate limiter and seeds fictional pricing, sliced metrics and captured-payment evidence. Its G-code is comment-only and labelled **LAB ONLY — NOT PRINTABLE**. It contacts no payment provider, printer, SMTP server or Redis instance. It is not an upload/storage integration environment and must never be deployed or bound to a public interface.

## Verification and repairs

Verification commands are the repository's Python tests, Ruff, mypy, frontend tests, ESLint and TypeScript checks. Tests exercise quote ownership, stale versions, supersession/expiry, snapshot immutability, mismatched/duplicate payment evidence, outbox replay, readiness, QA, fulfilment, single-use pairing, expiry/revocation, migration targeting and subprocess output. Browser inspection uses real sign-in/MFA and the test-only lab; it does not count fictional capture as a real Razorpay test.

The SQLite timestamp repair was reproduced at `/operations`: `GET /api/v1/quote-requests` returned analysis timestamps without a timezone, and the frontend rejected them. `schemas/base.py` now serializes persisted UTC timestamps explicitly while preserving Python datetime inputs. The same request now loads. Evidence is in `.local/workflow/analysis-before.png` and `analysis-after.png`; screenshots contain fictional lab data only.

Migration verification exposed another pre-existing problem: Alembic reused cached API settings, ignoring a newly selected test database. `migrations/env.py` now resolves fresh settings; the regression test deliberately caches a different disposable URL and verifies it is never created. An empty `xxx-development.db` inadvertently created during the initial test was inspected (zero users, requests or orders) and preserved as `.local/workflow/unintended-empty-development.db`. No existing database was overwritten or restored.

`tools/verify_migration_target.py --baseline` reproduces the same trigger using the actual tracked
Git baseline environment in copied migrations and disposable database paths. Without `--baseline`
it replays the current repair. The resulting database observations and screenshots are
`.local/workflow/migration-before.json`/`.png` and `migration-after.json`/`.png`. Neither replay opens
a user database. The before result selects the cached target; the after result selects the intended target.

Browser inspection also found that React reused an uncontrolled password input as the text MFA field. Separate keyed forms now remount the credential step and leave the MFA field empty. Screenshots never publish the lab password or TOTP secret.

The expired-quotation recovery trigger was exercised against disposable in-memory SQLite state,
with the service clock advanced two days. The original estimate creation rejected the `quoted`
request, and its existing-input reuse also returned expired estimates. `services/pricing.py`
now permits unaccepted quoted requests, skips expired reuse, and atomically versions the request
while superseding its old quotation. Replay creates request version 6; acceptance and concurrent
repricing tests pass. Redacted observations and pictures are `.local/workflow/estimate-refresh-before.json`/`.png`
and `estimate-refresh-after.json`/`.png`.

The live bridge replay reproduced HTTP 500 on a valid token in a fresh SQLite HTTP session.
`services/bridge.py` and `routes/bridge.py` now use database-backed ORM synchronization for the
expiry-guarded pairing/receipt updates, avoiding Python comparisons between persisted naive UTC
values and aware UTC cutoffs. The same fresh-session trigger now returns HTTP 200. The actual
standard-library client paired, heartbeated, downloaded the owner-authorized comment-only lab
artifact, verified its manifest and bytes, and acknowledged receipt. No physical command exists.
HTTP regressions also reject repeated pairing and consumed handoffs. Evidence is
`.local/workflow/bridge-pair-before.json`/`.png` and `bridge-pair-after.json`/`.png`.

### Verified revision — October 5, 2026

Codex implemented and reviewed this local slice directly, following the owner's instruction not
to use Opus review. The starting Git revision was `ff56774`; pre-existing user changes were
preserved. Nothing was committed, pushed or deployed.

- Python API/worker suite: **116 passed**, including a run treating unhandled test-thread warnings as errors.
- Frontend suite: **37 passed**.
- Ruff, mypy (60 source files), ESLint, TypeScript and the optimized Next.js build: passed.
- Normal password/MFA sign-in, empty MFA input, expired-MFA refusal, and desktop/mobile inspection: exercised.
- Latest API plus optimized frontend: lab queue → preparation → readiness → authorized artifact handoff → manual start record → QA → pickup readiness → collection; completed jobs leave the active queue.
- Buyer tracking at 390 px: no horizontal overflow; the same completed fictional order is visible only after buyer sign-in.

Browser images are `.local/workflow/final-owner-order.png` and `final-buyer-order-mobile.png`.
Readiness and physical lifecycle entries in these pictures are fictional operator test records,
not observed printer activity. The production-named frontend build was served only on loopback.
The final source/test/migration snapshot SHA-256 is
`e38cfb32e1d1f1453cc547e22cd502afde801716e214924ca360f2facb3393b2`
(sorted `rg --files` paths under web source, API source/tests/migrations, worker source/tests and bridge;
SHA-256 each file, then SHA-256 the resulting list). Documentation and ignored lab artifacts are excluded.

## Remaining decisions and release work

Rates, GST, delivery, cancellation/refund/reprint rules, legal wording, retention, sender/domain, support contacts and portfolio remain owner decisions. Policy-driven cancellation/refund/reprint and manual-UPI software are unfinished, not merely awaiting a switch. Real Razorpay and Orca acceptance, private S3/Redis production integration, AD5X control, protected Windows persistence/service recovery, restricted production database roles, monitoring and deployment remain release work. The public shell is a draft. Never promote lab databases, fictional profiles or Test Mode payments into production.

## Payment and notification setup

Keep `XXX_RAZORPAY_ENABLED=false` and `XXX_WORKFLOW_NOTIFICATIONS_ENABLED=false` until their owner gates are approved. Configure secrets locally through environment/secret management, never chat/source/URLs. Razorpay requires an approved Checkout name, mode-matching Key ID and distinct API/webhook secrets. Local/test environments reject live payment keys; production rejects Test Mode. Configuration validation is not merchant certification or launch authorization.

Configure the approved HTTPS webhook `/api/v1/payments/razorpay/webhook` for `payment.captured`, `order.paid`, `payment.authorized` and `payment.failed`. Payments in `/operations` offers reconciliation; buyers check status in their order detail. Never pay again while an earlier attempt is unresolved. Investigate stored receipt/account binding; do not switch accounts while unresolved intents remain without a reconciliation procedure. The worker's payment and notification tasks run independently of long analysis jobs.

Workflow notices reuse the approved SMTP sender/public web URL. Notifications in `/operations` shows accepted/failed/dead-letter status without raw destinations. Fix sender/network/recipient configuration before retry; unchanged-destination checks still apply. The stable Message-ID identifies an SMTP submission, not remote inbox delivery.

Protocol references: [Standard Checkout](https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/), [webhook validation/idempotency](https://razorpay.com/docs/webhooks/validate-test/), [receipt search](https://razorpay.com/docs/api/orders/fetch-all/) and [order payments](https://razorpay.com/docs/api/orders/fetch-payments/).

## Verified revision October 11 2026

Codex implemented and reviewed these additions directly without Opus or another implementation worker. The original dirty worktree was preserved. Nothing was committed, pushed, deployed or activated for real business operations.

- API/worker suite after dependency updates and shutdown repair: **147 passed**, treating unhandled test-thread warnings as errors. Web suite: **39 passed**. Ruff, mypy (66 source files), TypeScript and optimized Next.js **16.4.0** build passed. ESLint has no errors and one new framework warning about the existing full-page sign-out navigation; this warning remains explicit.
- Actual cookie/CSRF/MFA HTTP tests reject cross-role access, price tampering, unsigned/changed/oversized webhooks and unauthorized notification retries. Service tests cover payment correlation/refund conflicts, receipt recovery, replay, delayed reconciliation, changed email, backoff and crashed leases.
- Fresh PostgreSQL 17 lab migrated through `0009_notifications`. Five simultaneous Checkout requests caused one fictional provider create; six webhook deliveries caused one captured attempt/outbox/job. Manual operator records completed readiness, printing, QA and collection.
- Four concurrent notification publishers/delivery workers created **12** notices, each accepted once by the real SMTP transport into loopback Mailpit. This does not establish exactly-once SMTP crash recovery or external inbox delivery.
- A real `pg_dump`/`pg_restore` into another fresh lab database preserved migration head, one completed order, one captured attempt, one job, 12 sent notices and 14 audit rows. Existing databases were not restored/overwritten. Object-storage bytes and production restore are not covered.
- Latest owner sign-in/MFA and Notifications UI were inspected. Buyer payment/tracking was inspected on desktop and at 390 px using fictional gateway state, with no horizontal overflow. The real Razorpay popup/payment network was not exercised.
- The optimized 16.4.0 build was served on loopback after dependency updates. Normal owner password/MFA, Notifications, sign-out, separate buyer sign-in and unpaid order/payment boundaries were inspected again. Evidence: `notification-owner-next164.jpg` and `payment-buyer-next164.jpg`. Real Razorpay Checkout remains unverified.
- Real Redis 8.8 transport retained identifier-only stream entries, reclaimed an unacknowledged message and acknowledged it with zero pending entries. Ten concurrent limiter calls allowed exactly three and throttled seven; a real connection refusal failed closed. This transport test deliberately forces reclaim eligibility, not a full production lease/restart rehearsal. Evidence: `redis-lab.json`.

A genuine Checkout wiring failure was reproduced in the disposable buyer browser: valid POST returned HTTP 422 because an annotated dependency alias was incorrectly used as a callable, requiring nonexistent `args`/`kwargs` query parameters. `routes/payments.py` now binds the real CSRF function. Replay returned HTTP 200 and the authenticated fictional payment path queued once. Before/after pictures: `.local/workflow/checkout-wiring-before.jpg` and `checkout-wiring-after.jpg`. Different fresh lab IDs are intentional; the after picture proves local wiring, not real gateway operation.

Additional ignored evidence: `payment-http-after.json`, `payment-postgres.json`, `payment-buyer-mobile.jpg`, `notification-smtp-lab.jpg`, `notification-owner-lab.jpg` under `.local/workflow/`. All contacts/payments/printer records are fictional. The health test fixture now closes client/network resources so SQLite threads cannot outlive their event loop; this is verification cleanup, not a claimed production health repair.

Repeat the database/payment/mail race lab using these dedicated loopback containers:

```sh
docker run -d --name printflow-payments-lab-20261011 -e POSTGRES_DB=payment_lab -e POSTGRES_USER=payment_lab -e POSTGRES_PASSWORD=fictional-disposable-lab -p 127.0.0.1:55439:5432 postgres:17.10-alpine3.23
docker run -d --name printflow-mail-lab-20261011 -p 127.0.0.1:51025:1025 -p 127.0.0.1:58025:8025 axllent/mailpit:v1.30.0
.venv313/bin/python tools/verify_payments_postgres.py
```

If these named containers already exist, inspect/start rather than recreating/removing them. The tool validates them, creates a new database per run, migrates before seeding, and sends fictional contacts to loopback SMTP only. It never accepts arbitrary production URLs. The displayed password is fictional and must not be reused. Stop containers after verification without deleting retained database/dump evidence.

For the unpaid browser fixture use `workflow_lab:create_payment_lab`; for loopback mail use `workflow_lab:create_local_product_lab` with Mailpit running. Both keep the original loopback server commands above. The test-only provider simulates capture on its first status read; production never imports it. These fixtures do not prove actual slicing, storage, Redis or printer operation.

### Dependency security scan and storage gate

The actual pre-update runtime npm scan reported five affected package entries, including a
critical Next.js advisory. The installed Python scan reported 35 advisory entries (including
duplicate IDs) across seven packages. These are advisory findings, **not reproduced application
exploits**. No authentication bypass or source disclosure was observed in this application.

Next and its ESLint configuration are now 16.4.0, PostCSS 8.5.29, and compatible transitive web
packages were refreshed without forced downgrade. Python security floors are cryptography
50.0.2, PyJWT 2.15.1, httpx2 2.13.1, urllib3 2.8 and pytest 9.0.3; the local installer is pip
26.2.1. Repeated valid/invalid JWT tests reject expired, wrong-issuer, wrong-signature,
wrong-algorithm and future-not-before tokens. The existing application always constructs a fresh
options dictionary and never disables signature validation.

After-update `npm audit --omit=dev` and the installed Python `pip-audit --skip-editable --path`
scan both report **zero known vulnerabilities**. This is not a claim of zero security defects.
The complete npm scan still reports **five high development-tool entries**, all stemming from
unpatched `braces` through the Next ESLint plugin / fast-glob / micromatch chain. No runtime
dependency uses that chain in the lockfile; no untrusted pattern is supplied to linting here.
Do not suppress the advisory or force the suggested incompatible Next-14 ESLint downgrade.
This unresolved tooling advisory requires release review. Python ranges are not a complete
deployment lock; audit and lock the actual deployment environment before launch.

Raw ignored reports are `npm-audit-before.json`, `npm-audit-after.json`, `python-audit.json`
and `python-audit-after.json`. Primary references: [Next advisory](https://github.com/vercel/next.js/security/advisories/GHSA-6gpp-xcg3-4w24),
[PostCSS advisory](https://github.com/postcss/postcss/security/advisories/GHSA-fxqj-rqcc-2cmp),
[PyJWT options advisory](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-gvp8-978c-rx2q)
and [braces advisory/source references](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm).

The pinned `minio/minio:RELEASE.2025-09-07T16-13-09Z` failed to pull from Docker Hub;
`quay.io/minio/minio` with that exact tag returned 401. The [official source](https://github.com/minio/minio)
is archived/unmaintained. No unofficial mirror, replacement vendor or new licence was selected.
Real S3 privacy, exact POST-policy enforcement and object restore remain **unverified** pending a
trusted cached image or owner-approved maintained backend. Do not run the complete Compose stack
expecting its MinIO service to pull, or promote this incomplete stack into production.

Repeat the real Redis check without touching a business database:

```sh
docker run -d --name printflow-redis-lab-20261011 -p 127.0.0.1:56379:6379 redis:8.8.0-alpine3.23 redis-server --appendonly yes
.venv313/bin/python tools/verify_redis_lab.py
```

The script validates the exact image/name/loopback port, uses a fresh key namespace, and refuses
the connection-failure test if its designated unused port is occupied. Its report is a real
adapter/service check, not a complete model-upload-to-production Redis integration test. Start
an existing named lab rather than recreating it; stop it afterwards without removing its data.

Final source/test/migration/tool **and dependency-manifest** fingerprint:
`a6e6e6b7efdc2cbb9bbefd1f385d2a56bcc6903158ffe9a997edfb7df0b167cc`.
The sorted-file procedure includes web source, API source/tests/migrations, worker source/tests,
bridge and tools, plus web package/lock files and both Python project manifests. Each file is
SHA-256 hashed, then the resulting sorted list is hashed. Docs and ignored artifacts are excluded.
This is a local self-review checkpoint, not production approval or a committed revision.

### Worker shutdown repair — genuine before/after

Trigger: start the notice-enabled worker against a disposable real SQLite schema with the
`notifications` table absent. The notice task raised `OperationalError`; shutdown then awaited
the already-failed task again, propagating its error before storage, Redis or database cleanup.
The root cause was suppressing cancellation only, not collecting failures during task shutdown.

`services/worker/src/xxx_worker/main.py` now cancels/collects background tasks without overriding
the main-loop failure, then reaches all resource close hooks through nested cleanup boundaries.
The same schema error remains visible; this does **not** repair missing migrations or hide a
worker failure. The disposable replay changed all three worker cleanup-hook observations from
false to true, and the new regression plus full 147-test suite passed.

The reproduction is `services/worker/tests/worker_shutdown_lab.py`; its regression is
`test_worker_shutdown.py`. It uses a real missing-table database error, empty queue and resource
spies, no network/SMTP/payment/printer action, and always releases its own harness database.
The browser-rendered report is the actual trigger result, not a passing-test screenshot.
Ignored images `.local/workflow/worker-shutdown-before.jpg` and `worker-shutdown-after.jpg`
were captured before the repair and after the same replay and posted in the current task.
This verifies cleanup hook invocation, not Windows service recovery or physical hardware behavior.

## Academic report and frontend, October 15 2026

The academic presentation name is PrintFlow 3D. The public storefront, authentication
shell, request page and buyer/owner workspace received a restrained shared visual treatment,
self-hosted typography and light/dark appearance control. The owner rate-card editor now uses
three desktop columns and one mobile column. These changes do not replace authorization,
payment or printer contracts. No new frontend dependency was added. The generated parts
illustration is labelled illustrative and is not a manufactured portfolio photograph.

`submission/final-report/` contains a 55-page editable DOCX, checked PDF and a supporting ZIP
with 16 real local UI captures and 17 editable DOT/SVG/PNG diagrams. The body/tables use
Times New Roman 13 pt; the PDF embeds actual Times New Roman. The cover follows the supplied
layout and uses an official VIT Chennai logo extracted from the first page of the institution's
Mandatory Disclosures 2025–2026. The cover now includes the supplied names and register numbers
for Garima Nidhi, Pranesh S and Praanesh M B. The direct
request's CSE301L code was used; the sample's BCSE301L variant still needs owner confirmation.

The report covers the requested chapter order, a one-page abstract, 25 checked TOC targets,
24 functional requirements, eight non-functional requirements, nine module explanations,
24 representative test cases, references and implementation appendices. Every rendered page
was inspected; changed diagram/screenshot/table pages were checked again. The diagrams are
implementation explanations, not proof of commissioned external services. Figure 6.7 treats
Checkout callback feedback as an optional branch, not a prerequisite for webhook confirmation.

The standard API/worker suite passed **147** cases. A stricter run promoting unhandled-thread
warnings to errors had **146 passes and one failure** from intermittent aiosqlite thread cleanup
after an event loop closed; its root cause was not fully resolved during report work. This is
recorded in the report rather than claiming a passing strict run. The final web run passed
**39** tests, TypeScript/optimized build passed, and ESLint had no errors plus the existing
sign-out navigation warning. The last UI inspection included normal owner MFA, separate buyer
sign-in, a fictional lifecycle to completed pickup, and 390 px light/dark and pricing layouts.

All screenshot values, capture evidence and physical operator assertions are fictional local
test records. The browser lab still substitutes storage and rate limiting. No live payment,
real model slicing, physical QA, printer command, external email, deployment, commit or push
was performed for this report work. Existing production acceptance gates remain unchanged.

For an optimized browser fixture, set `API_INTERNAL_URL=http://127.0.0.1:8011` during **both**
the frontend build and start; the same-origin rewrite target is resolved at build time.
`READ_ME_FIRST.txt` contains the complete commands. The isolated preview was rebuilt with
that target and normal login was replayed after an initial local invocation used the default
port. This was a preview configuration correction, not an application backend repair.

Rebuild the document with `tools/build_final_report.py`, render with the bundled document
renderer and the installed Times New Roman fonts, then run `tools/package_final_report.py`.
That packaging check verifies the 55 page headings, one-page abstract, 25 TOC targets,
embedded fonts and ZIP integrity. `asset-manifest.json` records file hashes, source fingerprint
and evidence scope without credentials. Nothing in the report authorizes production launch.

## October 19: local print-station scope override and acceptance

The owner deferred business/SaaS work and asked for model → automatic printing. Current UI:
**http://127.0.0.1:3102/print**, not the older `/operations` preview on 3101. No account, cart,
pricing, payment, PostgreSQL, Redis or Docker dependency is used on this path. Existing business
code/data was preserved. New cart scaffolding from the earlier direction was removed before
any cart migration ran. No user data was deleted. No commit, push, deployment or real print.

Implementation: `services/bridge/print_station.py`, `ad5x_lan.py`, `moonraker_lan.py`,
`zmod_gcode.py`, `tools/run_print_station.py`, `apps/web/src/app/print`, shared model preview,
model-options schema and worker mesh transformation/slicing. One local operator, one active
job, generated filenames, private original/transformed artifacts, exact profile/artifact hashes,
submission-token idempotency, a durable physical-start intent, restart recovery and no physical
retry on uncertainty. Origin/Host/token checks protect loopback mutations. There is no public
printer URL or arbitrary G-code/temperature/motion console. Standard Moonraker does not prove
loaded IFS colour: ZMOD matching requires commissioning and a fresh operator check.

The friend's screenshot confirms a ZMOD installation and working Orca-to-printer sending.
Its "2.3.2" appears to refer to Orca, not the actual printer firmware. IP, printer/ZMOD versions,
physical build plate and working owner profiles still require on-site confirmation. See
`VISIT_PREFLIGHT.md`. All profiles remain **unapproved**, connection is absent and physical
starts are **disabled**. Textured PEI was selected explicitly for local slicing verification,
not asserted as the friend's installed plate. The complete official Orca 2.4.2 app was copied
from the previously verified vendor image into ignored `.local/print-station/OrcaSlicer.app`;
the station now pins that persistent executable, not the temporary mounted image.

Real browser acceptance, original/transformed files and measured Orca results:

- PLA 10 mm cube, 0.2 mm / 20% / one copy: **760 mg, 370 s**.
- PLA 10 mm cube, 0.15 mm / 20% / two copies: **1,490 mg, 613 s**, one G-code plate and two
  objects verified in the exported model-settings XML.
- PETG inch-based 0.4 × 0.6 × 0.8 prism, X90 then Y90, 0.1 mm / 90%: server and viewer both
  **15.24 × 20.32 × 10.16 mm**; **3,780 mg, 1,442 s** with explicit Textured PEI.
- Real Orca at 0.1 mm, two PLA copies → **loopback Moonraker simulator**: **1,510 mg, 904 s**,
  exactly one G-code upload containing the selected colour, ZMOD metadata, checksum and
  immediate-start request. This is software/protocol acceptance, **not a physical start**.
- The final optimized browser upload returned job `a8646d7cd5004a349ecd188752d00aee`, sliced
  successfully, and its downloaded ZMOD G-code SHA-256 matched the journal:
  `574be9585bfff9ffadb8dd0c2a636fb4aa6a23cf08c289f4b9ac36af87bb0b85`.

Genuine backend failure evidence and repair/replay:

1. Two-copy browser submission failed with `slicer_failed`. Orca's log said repetitions cannot
   be combined with slice-all; selecting plate 1 was also reset for raw STL input. Root cause:
   repetitions targets saved Orca plates, not raw STL/OBJ. `xxx_worker/slicing.py` now uses
   `--clone-objects N --arrange 1 --slice 0`, with a single-output-plate gate. Same trigger
   replay succeeded with two objects. Pictures: `.local/print-station/evidence/quantity-before.jpg`
   and `quantity-after.jpg`, posted in this chat.
2. The real PETG job failed because Orca defaulted to Cool Plate, which the PETG profile rejects.
   The station now requires an explicit `bed_type`, passes it into the process configuration,
   shows it in the UI, and revokes physical profile approvals when it changes. Same model,
   units, rotations, layer and infill replayed successfully with the **local verification**
   Textured PEI selection. Pictures: `.local/print-station/evidence/petg-before.jpg` and
   `petg-after.jpg`, posted in this chat. No physical plate assumption was approved.

Final verification: **179 API/worker cases passed, one opt-in real-Orca case skipped in the
ordinary suite**; that case separately passed against real Orca and the loopback simulator.
The focused station/transform/slicing run with real-Orca enabled passed **27** cases. Web tests:
**41 passed**. Ruff, API/worker mypy (72 files), bridge/launcher mypy with untyped-body checking
(five files), TypeScript and station-mode optimized Next build passed. ESLint: no errors, one
pre-existing sign-out navigation warning. No claim that the older intermittent aiosqlite
warnings-as-errors issue has been repaired. Pytest's repository path and generated-directory
lint ignores were corrected for the new station layout. The initial disabled-start test fixture
briefly attempted a read-only status call to its dummy private IP; it was corrected to configure
no driver. Subsequent transport tests address loopback only; no real upload/start was issued.

Desktop and 390 px mobile were personally inspected (375 CSS-pixel content width; no horizontal
overflow). Screenshots are real captures, not generated interfaces. Final capture:
`.local/print-station/evidence/final-station.jpg`; mobile: `mobile.jpg`. The React pass retained a
lazy-loaded Three viewer, stable callbacks, semantic form controls and explicit pending/error
states. A stale preview tab retained the expected build-time disconnect page; a fresh tab
verified the optimized application, home redirect, actual upload/slicing and G-code download.

Self-reviewed code fingerprint (SHA-256 of ordered `shasum -a 256` output for the 19 affected
station/preview/config/test source files):
`61c76bd6a2ed3120ee0e6fdd3632f0a92fa64deb36ace5e2a7e529f34842eb58`.
Codex implemented and reviewed directly after the earlier one-time Opus direction, per the
owner's explicit model-use limit. No additional architect/reviewer or implementation agent
was invoked. Coverage gap: no physical printer, installed ZMOD behaviour, real IFS matching,
thermal/mechanical calibration or Windows execution was tested. Unix process resource limits
are not a hostile-upload OS sandbox. Do not expose this local station publicly.

Current optimized launch (slicing only):

```sh
PRINTFLOW_PRINT_STATION=1 npm --prefix apps/web run build
.venv313/bin/python tools/run_print_station.py run --optimized-web
```

Stop before rebuilding or changing configuration; changing configuration while the station
holds its lock is refused. For development, omit `--optimized-web`. The existing 3100/3101
commerce environments and their data were not repurposed. At the printer, commission the actual
profiles/plate/connection/spool mapping and supervised ZMOD start first; only then explicitly
launch with `--enable-printer`. No automatic next-plate printing is supported.
