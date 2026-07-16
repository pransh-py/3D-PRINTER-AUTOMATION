# `xxx` Product Requirements

- Status: Draft implementation contract
- Target: One-week MVP
- Market: Chennai, Tamil Nadu, with fulfillment across India
- Currency: INR

## Product outcome

Build a public website through which buyers can submit printable 3D models, receive a reproducible system estimate, obtain an owner-approved quotation, pay through a manually verified UPI flow, and track the job through printing and fulfillment. Give the business owner one operations console for pricing, approval, payment verification, queue management, printing, and delivery.

The product must support one FlashForge AD5X connected to an always-on Windows computer. Physical printer control is mediated by a local bridge and owner safety gates; internet buyers never receive general printer control.

## Actors

### Buyer

- Registers, verifies an email address, signs in, and manages their own profile.
- Uploads models and selects supported print requirements.
- Reviews estimates and owner-approved quotations.
- Pays outside the website using the displayed UPI QR/VPA and submits the UTR/reference.
- Tracks payment review, queue position, production, quality check, and fulfillment.
- May cancel only while the order is in a cancellable state.

### Owner

- Uses a separately provisioned owner account with MFA; there is no public owner registration.
- Configures materials, colors, print presets, rates, minimum charges, and fulfillment options.
- Reviews system estimates and approves, changes, or rejects quotations with reasons.
- Verifies UPI payments against the actual bank/UPI record.
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
7. The buyer accepts the quotation and receives the business UPI QR/VPA plus the exact payable amount and order reference.
8. After paying, the buyer submits the UTR/reference. The order remains `PAYMENT_REVIEW` until the owner independently verifies it.
9. A verified order enters the print queue. The owner prepares the printer and authorizes the job.
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

## Payment contract: manual UPI MVP

- Display only owner-configured UPI beneficiary information and a QR encoding the exact amount and unique order reference where supported.
- Never collect a buyer's UPI PIN, banking password, OTP, or card details.
- A buyer submission contains a UTR/reference and optional evidence; it is a claim, not proof of payment.
- Only the owner can mark a payment `VERIFIED`, after checking the actual beneficiary account.
- Record the verifier, time, amount, reference, and immutable audit event.
- Reject duplicate UTR/reference values and flag reused evidence, but do not treat those checks as bank confirmation.
- A verified payment amount must exactly match the accepted quotation unless the owner follows a recorded exception flow.
- Orders cannot enter the print queue from client-side state or an unverified payment claim.
- Refunds are manual and must be recorded with a reason and reference in the MVP.

Razorpay is explicitly deferred. Its later integration will replace manual verification with signed server-to-server payment events while preserving the order/payment state machine.

## Order state model

```text
DRAFT
  -> ANALYZING
  -> ESTIMATE_READY | ANALYSIS_FAILED
  -> OWNER_REVIEW
  -> QUOTED | REJECTED
  -> QUOTE_ACCEPTED | QUOTE_EXPIRED | CANCELLED
  -> PAYMENT_PENDING
  -> PAYMENT_REVIEW
  -> PAID_VERIFIED | PAYMENT_REJECTED
  -> QUEUED
  -> PREPARING
  -> READY_TO_PRINT
  -> PRINTING
  -> QA
  -> READY_FOR_PICKUP | OUT_FOR_DELIVERY | SHIPPED
  -> COMPLETED
```

`PRINT_FAILED`, `ON_HOLD`, `CANCELLED`, and `REFUND_PENDING/REFUNDED` are controlled exception states. State transitions are enforced server-side with role checks, preconditions, idempotency, and audit events.

## Physical printer safety

- The owner, not an internet buyer, controls preparation and physical print authorization.
- Starting requires a paid-and-verified order, first-in-queue authorization, an idle/healthy bridge and printer, an approved sliced artifact, and an owner readiness acknowledgement.
- The bridge uses job-specific idempotency keys so retries cannot start duplicate prints.
- The owner can pause/cancel where the verified adapter supports it. Buyers may request cancellation but do not send machine commands.
- Automatic consecutive printing is out of scope because the AD5X does not remove parts or prepare the bed between jobs.
- A manual export/send fallback must exist if reliable direct control cannot be proven on the available firmware.

## Owner console MVP

- Dashboard of requests requiring action, payments awaiting verification, queued jobs, printer health, and fulfillment work.
- Quote detail with preview, analysis evidence, cost breakdown, overrides, rejection reason, and expiration.
- Payment-verification view with duplicate-reference warnings and audit history.
- Queue with explicit ordering, hold/release, preparation checklist, start, failure, reprint, and completion actions.
- Pricing/material configuration with effective dates and immutable snapshots on issued quotes.
- Buyer/order search and minimal customer-support notes.

## Public-site MVP

Use Padaiparai as directional inspiration for a service-led presentation, but do not copy protected branding, text, images, or layout. Required public sections are hero/quote CTA, capabilities, supported materials, process, example work supplied by the owner, FAQs, contact, terms, privacy, refund/cancellation, and shipping/pickup information.

## Explicitly outside the one-week MVP

- Razorpay or automated bank settlement.
- Automatic courier rating, booking, labels, and tracking webhooks.
- Buyer-controlled printer access.
- Automatic bed clearing or unattended back-to-back jobs.
- CAD editing, generative model creation, or guaranteed geometry repair.
- Social login, coupons, loyalty, marketplace sellers, multiple owners, or multiple printers.
- Native mobile applications.

## MVP acceptance criteria

- A new buyer can verify an account, upload a supported model, and receive a repeatable slicer-backed estimate.
- An owner can approve/reject the estimate and issue an immutable final quotation.
- A buyer can accept the quote, see UPI instructions, and submit a payment reference.
- Only the owner can verify payment; only a verified paid order can be queued.
- The owner can safely prepare/start a queued job through the bridge or documented manual fallback.
- Both actors see correct status history without accessing another buyer's private models or orders.
- Security, audit, backup, failure-recovery, and deployment checks in `docs/SECURITY.md` and `docs/ROADMAP.md` pass.

## Outstanding stakeholder decisions

1. Material types, brands, colors, spool costs, and current stock.
2. Nozzle sizes, layer heights, infill choices, support policy, multicolor offering, finishing, and design assistance.
3. Machine hourly rate, labor/setup charges, minimum order, waste/failure factor, tax/GST treatment, and quote lifetime.
4. Pickup address/rules, local-delivery area/rate, and pan-India shipping calculation.
5. Business UPI VPA/QR, beneficiary display name, and verification procedure.
6. Business legal entity/GST status, terms, privacy/retention period, prohibited content, refund/cancellation, and liability wording.
7. Windows version, Orca-Flashforge installation, AD5X firmware, LAN/WAN mode, Printer ID pairing, and hardware test access.
8. Domain, email sender, support contact, branding, and owner-supplied portfolio content.
