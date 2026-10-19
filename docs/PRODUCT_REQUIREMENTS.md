# `xxx` Product Requirements

## Current scope override — October 19, 2026

The owner explicitly deferred business/SaaS work: build a local single-printer station that
accepts a model, slices it and starts printing automatically. No identity, quotation, cart,
payment or fulfilment prerequisite belongs on this path. Those existing modules remain intact
as future work, not the current user journey. Confirmed stock: PLA red/white/black; PETG black/orange.
The new `/print` page and loopback station run separately from the commerce API and database.
The friend's screenshot confirms ZMOD and working Orca-to-printer sending. "2.3.2" appears to
answer the Orca-version question, not establish the printer firmware. The owner's LAN address
was subsequently configured and read-only Moonraker status verified on October 20; no API key
was required by the existing LAN configuration. Stock firmware remains unconfirmed; ZMOD's
commissioning output reports USB 1.7.3 and updated version 1.7.3-83.

The local verification explicitly uses a Textured PEI profile setting to exercise PETG;
this was initially **not confirmation of the friend's physical build plate**. The owner has
subsequently confirmed Textured PEI, as recorded below. PLA was approved after the supervised
cube commissioning described below; PETG remains unapproved for physical printing.
Use hash-pinned, owner-reviewed working profiles, not made-up temperatures or printer macros.

### Owner-confirmed printer setup — October 20, 2026

The owner confirms a **0.4 mm nozzle**, **220 × 220 × 220 mm build volume**, **Textured PEI**
plate, and PLA spools assigned as white in IFS slot 1, black in slot 2 and red in slot 3.
Read-only `zmod_color` metadata agrees with these material/colour registrations and reports
exact registered hex values `#FFFFFF`, `#161616`, and `#F72224`, respectively. Use these
registered colours for the local mapping rather than assuming pure black/red preview values.

This is the owner's physical-spool confirmation plus printer colour metadata, not a verified
filament-presence reading: the initial status reported `ifs=false` and `hasFilament=false` for
the slots, with the native screen active (`display=true`). Observed stored settings are
`scan_file_colors=1`, `silent=1`, `auto_assign_colors=2`; this is not the stricter colour-match
commissioning configuration described in the setup guide. No printer setting is changed by
recording these observations. The owner supplied the Orca profile bundle described below;
supervised ZMOD start/colour commissioning subsequently passed for PLA as recorded below.
Keep uncommissioned material profiles disabled.

### Owner-supplied Orca bundle — October 20, 2026

The supplied `Flashforge AD5X 0.4 nozzle - M1.orca_printer.zip` contains the custom M1
machine, `0.20mm Standard @FF AD5X - custom_name` process and `Numakers PLA` filament.
Its SHA-256 is `db90047bc8ae245e4dd1e7754033406f618283d5be1e965f1e2b02484b2d44ad`.
Keep the original and compiled profiles in private local runtime storage. Resolve the named
vendor parents against the installed official Orca 2.4.2 resources, preserving the owner's
explicit functional settings and start/end G-code. The export metadata says `2.3.2.60`;
resolved inherited defaults therefore come from the installed version, not a claim of exact
equivalence with that older version.

The compiled PLA profile replaces the demo PLA profile for new slices. The station still
applies the chosen layer height, infill, quantity, colour, support and confirmed plate settings.
The exported filament cost field does not override the owner's INR 3/g + INR 10/hour rates.
Old slice artifacts and estimate snapshots retain their original profile and measured values.
PETG still uses its unapproved software-test profile.

Real Orca tests pass at all three supported layer heights. The owner's generated start code
has no explicit `G28` homing or `M109` nozzle-temperature wait. Preserve it rather than inventing
replacement commands; verify the installed ZMOD start wrapper and actual colour selection
under supervision before approving physical operation.

### Supervised commissioning authorization — October 20, 2026

The owner explicitly requested the small test print and subsequent website activation, then
confirmed a clear installed bed, ready red PLA in slot 3 and a person beside the printer able
to stop it. The commissioning job is the already verified 20 mm cube at 0.20 mm, 20% infill,
one copy, supports off, Textured PEI, 220 C nozzle and 55 C initial bed from the supplied profile.
Keep website starts disabled during this first operator-controlled commissioning run.
Preserve a durable one-send intent and telemetry evidence; do not retry an ambiguous start.

A non-moving `GET_ZCOLOR SILENT=1` query refreshed native-screen metadata and confirmed
`ifs=true` with red PLA in slot 3. The earlier `ifs=false` value was cached and did not prove
a disconnected IFS. Native-screen slot-presence fields from the general status object are
still not authoritative. Installed `_PRINT_FILE`, `SDCARD_PRINT_FILE` and related ZMOD macros
were inspected read-only. ZMOD's Moonraker fork routes native-screen starts through
`_PRINT_FILE` and native `/printGcode`, rather than executing the exported purge sequence
without the native preparation. Do not change the screen mode or inject guessed start code.

Set only the documented `AUTO_ASSIGN_COLORS=30` strict matching policy (previously 2);
scanning and silent-start are already 1. No temperature, purge, motion, firmware or screen
setting is changed. After a successful supervised cube and confirmed red first layer,
record PLA profile/start review and enable the website. PETG remains unapproved.

The one-send test completed at 100% for its exact filename, with 737.56 seconds of reported
print duration (native preparation is additional). The owner confirmed the red first layer
and normal adhesion/motion. The native finish sequence subsequently turned off both heaters
and reset SD/print status to idle. Keep the supplied start/end code unchanged: the bed's
briefly retained target during finishing is not a persistent heater state.

The regular approval commands recorded PLA profile approval and ZMOD start review. The
backend now runs with `--enable-printer`. PLA red/white/black mappings are available with
a fresh per-job operator readiness confirmation; PETG remains slicing-only. The physical
test covered red slot 3, not a print in every offered colour. Activation never starts an
old sliced estimate automatically. The API's readiness and unapproved-PETG guards were
checked without sending another print.

### Local estimate clarification — October 20, 2026

The owner requested automatic monetary estimates after slicing and confirmed **INR 3 per gram
of filament and INR 10 per printing hour**. Use these rates for the local station's offered
materials; duration is proportional to measured seconds, not rounded up to whole hours.
The estimate is material plus printing time, using Orca's measured filament and duration for
the entire plate. Quantity is already included in those metrics and must not be multiplied
again. Reuse pricing-v1 integer paise calculations, rounding each component upward to paise.
No minimum, setup fee, tax, delivery or other adjustment has been supplied; these are outside
this two-component estimate, not asserted to be free or tax-exempt.

Store rates and the calculated breakdown with each successful slice. Existing unpriced slices
may be estimated explicitly with the confirmed rates; changing rates must not rewrite prior
estimate snapshots. Rates are private local configuration, never accepted from upload options.
This adds estimates to the local path without requiring accounts, checkout or physical starts.

The requirements below describe the preserved business workflow unless stated otherwise.

- Status: Draft implementation contract
- Target: One-week MVP
- Market: Chennai, Tamil Nadu, with fulfillment across India
- Currency: INR

## Product outcome

Build a public website through which buyers can submit printable 3D models, receive a reproducible system estimate, obtain an owner-approved quotation, pay through Razorpay Checkout, and track the job through printing and fulfillment. Give the business owner one operations console for pricing, approval, payment exceptions, queue management, printing, and delivery.

The product must support one FlashForge AD5X connected to an always-on Windows computer. Physical printer control is mediated by a local bridge and owner safety gates; internet buyers never receive general printer control.

## Actors

### Buyer

- Registers, verifies an email address, signs in, and manages their own profile.
- Uploads models and selects supported print requirements.
- Reviews estimates and owner-approved quotations.
- Pays through Razorpay Checkout using an enabled method such as UPI, card, or net banking.
- Tracks payment processing, queue position, production, quality check, and fulfillment.
- May cancel only while the order is in a cancellable state.

### Owner

- Uses a separately provisioned owner account with MFA; there is no public owner registration.
- Configures materials, colors, print presets, rates, minimum charges, and fulfillment options.
- Reviews system estimates and approves, changes, or rejects quotations with reasons.
- Reviews payment exceptions, reconciliation failures, refunds, and explicitly issued manual-UPI fallback claims.
- Controls queue order, printer readiness, print start, failure handling, QA, and fulfillment.
- Can view audit history but cannot silently rewrite historical quotation or payment facts.

### Local print bridge

- Runs on the business's Windows computer and makes outbound authenticated connections only.
- Reports printer/bridge health and executes owner-authorized, job-specific commands.
- Never accepts arbitrary buyer files, G-code, temperatures, or commands.

## MVP customer journey

1. A buyer browses services, supported materials, example work, process, and policies.
2. The buyer creates an account and verifies their email.
3. The buyer creates a quote request and uploads one to five model files.
4. The system validates each file, extracts safe metadata, generates a preview, and slices it using an approved AD5X preset.
5. The system calculates an estimate from sliced filament usage, print time, configured business rates, quantity, and applicable adjustments.
6. The owner reviews the request and either rejects it with a reason or issues a time-limited final quotation.
7. The buyer accepts the quotation. The API creates a Razorpay Order for the exact accepted amount and returns a checkout session reference.
8. The buyer completes Razorpay Checkout. The browser may show an immediate result, but the order remains `PAYMENT_PROCESSING` until the API validates signed provider evidence and reconciles the provider order, payment, amount, and currency.
9. A captured and confirmed payment moves the order to `PAID_CONFIRMED` and creates one print-queue effect. The owner prepares the printer and authorizes the job.
10. The local bridge sends only the approved sliced artifact and reports progress and terminal status.
11. The owner performs QA and records pickup, local delivery, or shipment details.
12. The buyer sees the final status and fulfillment information.

## Upload contract

Accept these source-model formats for the MVP:

- STL (`.stl`)
- 3MF source project/model (`.3mf`)
- OBJ (`.obj`)
- STEP (`.step`, `.stp`)

Apply these initial limits until production measurements justify changes:

- 100 MB per file.
- Five model files per quote request.
- Server-side file signature and structure checks; extensions and browser MIME types are not trusted.
- Geometry, decompression, polygon, processing-time, memory, and output-size limits.
- Uploaded G-code, pre-sliced printer files, ZIP, AMF, SVG, executables, and nested archives are rejected.
- Every source is re-sliced with an owner-approved AD5X profile. Buyer-supplied machine instructions are never executed.

Model repair may be suggested but must not silently change dimensions or functional geometry. The buyer must approve material changes to the model.

## Estimation and quotation

The slicer must provide at least:

- Printable/not-printable result and reason.
- Bounding dimensions and AD5X build-volume fit.
- Filament usage by material/color, including support and purge waste where available.
- Estimated print duration.
- Selected nozzle, layer-height, infill, support, and quantity assumptions.
- Warnings for thin walls, unsupported regions, non-manifold geometry, or uncertain scale when detectable.

Use a versioned pricing snapshot:

```text
material = sliced grams by material × owner rate per gram
machine = sliced duration × owner machine rate
subtotal = material + machine + setup/labor + finishing + complexity/multicolor
risk_adjusted = subtotal × configured waste/failure factor
quote = max(risk_adjusted, minimum order) + tax + delivery/shipping
```

Every final quotation records the exact inputs, rates, slicer/profile versions, owner adjustments, expiration, and reason for any override. Later configuration changes must not alter an accepted quotation.

Pricing values, initial materials/colors, nozzle offerings, quality presets, finishing services, tax treatment, and shipping rules remain stakeholder decisions and block production quotation accuracy.

## Payment contract: Razorpay Checkout primary

- The FastAPI API creates every Razorpay Order server-side from the immutable accepted-order snapshot. The browser cannot choose or alter the amount, currency, receipt, local order, or provider order ID.
- Razorpay Checkout is the primary buyer payment surface. PrintFlow never collects or stores a buyer's UPI PIN, banking password, OTP, CVV, or full card details.
- The public Razorpay Key ID may be delivered to the web client. The Key Secret and webhook secret remain server-side secrets and must never appear in client bundles, logs, URLs, analytics, or repository files.
- The checkout callback is used only for immediate buyer feedback. It must be signature-verified server-side using the local order's stored Razorpay Order ID, and it cannot independently create a paid transition or print job.
- The authoritative automated transition requires either a signature-valid `payment.captured`/`order.paid` webhook reconciled against current provider state, or a server-authenticated API observation. Both require exact local/provider order correlation, exact INR amount and a current captured, unrefunded payment against a paid order. API evidence is explicitly distinguished from webhook signature evidence.
- Webhooks are verified over the raw request body, deduplicated by provider event ID, accepted out of order, persisted as immutable evidence, and processed idempotently.
- One database transaction records the captured payment, moves the order to `PAID_CONFIRMED`, appends audit evidence, and writes one print-job outbox event.
- `authorized`, failed, mismatched, unsigned, replayed, unknown, or client-only results never enter the print queue.
- Refunds require an owner action, a recorded reason, provider correlation, webhook/API reconciliation, and an immutable audit trail. Exact cancellation and refund eligibility remains an owner-approved policy decision.
- Manual UPI is a disabled-by-default fallback. The owner may explicitly issue a fallback intent after gateway or account failure; a buyer UTR/evidence submission remains an unverified claim until the owner checks the actual beneficiary account with recent MFA.

See `docs/adr/0007-razorpay-primary-payments.md` for the approved provider boundary and failure model.

## Order state model

```text
DRAFT -> ANALYZING -> ESTIMATE_READY | ANALYSIS_FAILED
ESTIMATE_READY -> OWNER_REVIEW -> QUOTED | REJECTED
QUOTED -> QUOTE_ACCEPTED | QUOTE_EXPIRED | CANCELLED
QUOTE_ACCEPTED -> PAYMENT_PENDING
PAYMENT_PENDING -> PAYMENT_PROCESSING | PAYMENT_FAILED | PAYMENT_REVIEW
PAYMENT_PROCESSING -> PAID_CONFIRMED | PAYMENT_FAILED | PAYMENT_REVIEW
PAYMENT_REVIEW -> PAID_CONFIRMED | PAYMENT_REJECTED
PAID_CONFIRMED -> QUEUED -> PREPARING -> READY_TO_PRINT -> PRINTING -> QA
QA -> READY_FOR_PICKUP | OUT_FOR_DELIVERY | SHIPPED
READY_FOR_PICKUP | OUT_FOR_DELIVERY | SHIPPED -> COMPLETED
```

`PRINT_FAILED`, `ON_HOLD`, `CANCELLED`, and `REFUND_PENDING/REFUNDED` are controlled exception states. State transitions are enforced server-side with role checks, preconditions, idempotency, and audit events.

## Physical printer safety

- The owner, not an internet buyer, controls preparation and physical print authorization.
- Starting requires a paid-and-confirmed order, first-in-queue authorization, an idle/healthy bridge and printer, an approved sliced artifact, and an owner readiness acknowledgement.
- The bridge uses job-specific idempotency keys so retries cannot start duplicate prints.
- The owner can pause/cancel where the verified adapter supports it. Buyers may request cancellation but do not send machine commands.
- Automatic consecutive printing is out of scope because the AD5X does not remove parts or prepare the bed between jobs.
- A manual export/send fallback must exist if reliable direct control cannot be proven on the available firmware.

## Owner console MVP

- Dashboard of requests requiring action, payment exceptions/reconciliation failures, queued jobs, printer health, and fulfillment work.
- Quote detail with preview, analysis evidence, cost breakdown, overrides, rejection reason, and expiration.
- Payment-operations view with provider correlation, captured/failed status, reconciliation controls, refund actions, fallback review, and audit history.
- Queue with explicit ordering, hold/release, preparation checklist, start, failure, reprint, and completion actions.
- Pricing/material configuration with effective dates and immutable snapshots on issued quotes.
- Buyer/order search and minimal customer-support notes.

## Public-site MVP

Use Padaiparai as directional inspiration for a service-led presentation, but do not copy protected branding, text, images, or layout. Required public sections are hero/quote CTA, capabilities, supported materials, process, example work supplied by the owner, FAQs, contact, terms, privacy, refund/cancellation, and shipping/pickup information.

## Explicitly outside the one-week MVP

- Saved cards, subscriptions, payment links as the primary checkout, split settlements, and multi-provider routing.
- Automatic courier rating, booking, labels, and tracking webhooks.
- Buyer-controlled printer access.
- Automatic bed clearing or unattended back-to-back jobs.
- CAD editing, generative model creation, or guaranteed geometry repair.
- Social login, coupons, loyalty, marketplace sellers, multiple owners, or multiple printers.
- Native mobile applications.

## MVP acceptance criteria

- A new buyer can verify an account, upload a supported model, and receive a repeatable slicer-backed estimate.
- An owner can approve/reject the estimate and issue an immutable final quotation.
- A buyer can accept the quote, open Razorpay Checkout, complete a test payment, and see a processing/confirmed result.
- Only signature-valid, server-correlated captured payment evidence or an owner-verified fallback can mark the order paid; only a confirmed paid order can be queued.
- The owner can safely prepare/start a queued job through the bridge or documented manual fallback.
- Both actors see correct status history without accessing another buyer's private models or orders.
- Security, audit, backup, failure-recovery, and deployment checks in `docs/SECURITY.md` and `docs/ROADMAP.md` pass.

## Outstanding stakeholder decisions

### October 20 trusted LAN access

The owner requested access to the print station from other devices on the same LAN.
An explicit `run --lan-host <private IPv4>` option may expose the web interface at that
one address; the API remains on loopback behind the website proxy. This is the same
trusted operator station, with access to its models, activity and commissioned print
controls. It adds no public internet hosting, accounts or business checkout. Existing
profile approvals, one-active-job protection and per-print readiness checks still apply.
The owner will submit print jobs personally through the website.

For customer-style testing, the owner requested that the inline printer-readiness
checkbox be removed. Real printing stays available, with a fresh operator confirmation
only after choosing the action that starts a print. Cancelling sends no upload or start;
slicing for an estimate requires no operator confirmation. The backend readiness
attestation and commissioned-profile checks remain enforced.

The buyer view shows the estimated total rather than the owner's filament/hourly rates
or separate material/machine charges. It also omits the printer-start capability banner
and internal single-plate/back-to-back-print explanation. Pricing calculations, quantity
validation and operator confirmation at print start continue to apply.

The buyer must see the sliced estimate inside Review & print before choosing to print.
The website first uploads/slices without dispatch, then shows the total and a separate
`Print for INR …` action. Model or settings changes invalidate the displayed estimate.
`POST /api/printer/jobs/{job_id}/start` accepts a fresh UUID submission token, the
expected total in integer paise and explicit operator readiness. It claims a sliced job
atomically, verifies the stored price, current preparation context and artifact hashes,
and dispatches those same prepared bytes once. It does not re-upload or re-slice the
model or recalculate an accepted price. Conflicting starts, stale preparation, changed
artifacts and unapproved profiles are rejected; ambiguous dispatch is never resent.

Cancellation/stopped-job detection is automatic. Preserve Moonraker's raw job state,
SD execution and heater targets, and optionally read the paired native FlashForge status
on the existing LAN address. Native credentials stay in the private station configuration.
An explicit cancellation with inactive execution and heaters off is terminal. For the
native-screen case that leaves Moonraker in standby, require native ready with no file,
an empty queue, inactive execution, heaters off, a start older than 90 seconds and at
least 12 seconds of consistent observations. Mark that attempt stopped (not completed),
unless matching Moonraker history supplies an explicit completion/cancellation. No resend
or next automatic print follows. Heating, motion, paused jobs, uncertain status or loss
of either configured connection must never be treated as a cancelled/finished job.

### October 19 delivery correction

#### Robu-style standalone configurator (afternoon correction)

The owner supplied screenshots/audio and explicitly selected **cart → immediate test checkout**.
The customer page must use a model-preview/upload column and four progressive steps: print quality,
material/colour, infill, finalize. Only actual configured profile combinations are selectable; the
0.6 mm nozzle option is excluded. Preserve PrintFlow branding rather than Robu's electronics store,
stock, reviews, delivery promises or prices. Units and applied X-then-Y rotation must reach actual
worker geometry and the accepted snapshot, not be decorative preview controls. Unit/rotation edits
are supported for STL/OBJ; native-unit 3MF/STEP retain their file units/orientation, explicitly shown.

The owner then explicitly superseded business/cart work: **business later; make the local automation
module work first**. The current implementation target is a small local print station, not another
SaaS platform: upload → configure → validate/slice → send to the AD5X → observe print start. No account,
quotation, cart, payment, PostgreSQL or Redis is required on this path. Preserve the earlier storefront
without expanding it. Newly started cart scaffolding was removed before any database migration.

Confirmed materials/colours are PLA (red, white, black) and PETG (black, orange); do not invent ABS stock.
One supervised job at a time; multiple copies must fit a single plate rather than automatically
printing consecutive jobs on an uncleared bed. Physical dispatch is disabled until the station has
reviewed profiles, private LAN credentials, a live AD5X status and explicit operator readiness for
that job. Persist a start intent before network transmission; ambiguous responses/restarts must never
resend a potentially accepted print. Hardware commissioning remains necessary before claiming a real
automatic print. Printer credentials stay local and are never entered in chat or browser bundles.

The owner confirmed Robu.in as the ordering-flow reference and requested one initial
Claude Opus 5.5 analysis only, followed by Codex implementation and self-review.
Prepare test checkout and owner-approved quotations; live gateway activation and invented
selling prices remain prohibited. The owner confirmed the FlashForge AD5X; there is no separate
automation tool named “Eleksai.” Robu.in is the customer-ordering reference, not a printer driver.

The implementation contract for selectable print requirements is an owner-maintained preset
manifest. Each offering binds one material code, stated available colours, and three standalone
machine/process/filament profiles to their combined SHA-256. Layer height, nozzle diameter,
infill, support policy, wall count and filament type shown to buyers must come from those
verified profile files, not hardcoded storefront claims. Only offerings with an active material
rate can be ordered. An empty catalogue must display a setup state, never invented stock.
The request captures the selected public specification and colour. Idempotent retries cannot
change it. The worker must resolve the same preset and hash before slicing; changed or missing
profiles cannot silently fall back to the global default. Issued quotations and accepted orders
freeze that specification. Legacy requests retain their existing single-profile path and are
identified as having no captured print specification.

The worker automatically calculates the first estimate after a successful matching preset slice,
using only the active owner-approved rate card. A persisted-state recovery pass handles a crash
between slicing and calculation. Repeated passes cannot replace an estimate or owner quotation.
System calculations have no human actor; owner quotation approval remains a separate MFA action.

For this first selectable-preset flow, source dimensions are preserved. STL and OBJ are in
millimetres; 3MF retains its declared units. No scale, rotation, free-form printer instructions,
multicolour mapping or buyer-supplied G-code is offered as an executed option. Requirements in
notes do not override the displayed preset. Material colour is an operator-loaded spool choice,
not a claim of automatic filament-slot mapping. Real gateway and physical-printer verification
remain separate acceptance gates.

The owner subsequently confirmed the AD5X and approved private local-folder storage for the
single-machine setup. The local adapter is permitted only in development/test with loopback
web origins and an explicit private directory. Upload bodies use buyer-authenticated,
CSRF-protected same-origin PUT requests bound to existing upload intents, with exact byte-count,
expiry, checksum and ownership checks. Files are not publicly served; the worker uses the same
private adapter. Production and staging keep the S3 adapter and reject this local configuration.

The owner confirmed local-only implementation and verification on 5 October 2026. No business
rates, GST treatment, delivery charges or cancellation/refund rules are approved. Razorpay will
be configured later by the owner. The 11 October full-product request expands implementation,
not permission to invent facts or activate live systems. Checkout/webhook/reconciliation and
transactional email now exist but remain disabled by default. There is no public paid-state
mutation or direct printer dispatch. `LOCAL_WORKFLOW.md` records the
implemented behavior; acceptance criteria above describe the intended production MVP.

1. Material types, brands, colors, spool costs, and current stock.
2. Nozzle sizes, layer heights, infill choices, support policy, multicolor offering, finishing, and design assistance.
3. Machine hourly rate, labor/setup charges, minimum order, waste/failure factor, tax/GST treatment, and quote lifetime.
4. Pickup address/rules, local-delivery area/rate, and pan-India shipping calculation.
5. Razorpay merchant onboarding/KYC owner, live/test credentials, enabled methods, settlement/reconciliation procedure, account-level capture setting, webhook secret rotation, and manual-UPI fallback beneficiary/procedure.
6. Business legal entity/GST status, terms, privacy/retention period, prohibited content, refund/cancellation, and liability wording.
7. Windows version, Orca-Flashforge installation, AD5X firmware, LAN/WAN mode, Printer ID pairing, and hardware test access.
8. Domain, email sender, support contact, branding, and owner-supplied portfolio content.
