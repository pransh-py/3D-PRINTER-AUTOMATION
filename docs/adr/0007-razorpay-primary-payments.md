# ADR 0007: Razorpay as the primary payment gateway

- Status: Accepted
- Date: 26 August 2026
- Decision owner: Business owner

## Context

The earlier MVP plan required buyers to pay outside PrintFlow, submit a UTR or screenshot, and wait for the owner to verify the real beneficiary account. That flow preserves safety but creates avoidable manual work, slower queue entry, weak buyer feedback, and a larger payment-evidence privacy surface.

PrintFlow needs an online Indian payment path that supports UPI and common alternatives while preserving three invariants:

1. The accepted quotation is the sole source of amount and currency.
2. Browser state cannot mark an order paid.
3. Payment retries, callbacks and webhooks create at most one queue effect.

## Decision

Use Razorpay Standard Checkout as the primary payment provider. Create Razorpay Orders only from FastAPI after an accepted quote has produced an immutable local order snapshot.

The automated paid transition requires all of the following:

- A valid raw-body webhook signature or an explicitly labelled server-authenticated API observation.
- A deduplicated provider event ID (API observations have separate locally generated IDs).
- A stored local payment intent whose Razorpay Order ID matches the event.
- Exact INR amount and currency agreement with the accepted order.
- A current paid order and captured, unrefunded payment, obtained through authenticated Razorpay API reads. A signed `payment.captured`/`order.paid` event alone cannot bypass current-state correlation.

The checkout callback may provide immediate buyer feedback after server-side signature verification, but it is not authoritative enough to enqueue work. `payment.authorized` is not a paid transition.

The confirmed transition is transactional: persist provider payment evidence, set the payment intent to captured, set the order to `PAID_CONFIRMED`, append an audit event, and write one print-job outbox event.

Manual UPI remains a disabled-by-default fallback. It can be issued only by the owner when the gateway/account path is unavailable or an approved exception applies. A fallback claim still requires independent owner verification with recent MFA and reaches the same `PAID_CONFIRMED` domain transition.

## Trust boundary

- The browser receives only the Razorpay Key ID, local checkout details and provider Order ID needed for Checkout.
- Razorpay Key Secret and webhook secret are server-only deployment secrets.
- PrintFlow does not collect or store UPI PINs, OTPs, banking passwords, CVVs or full card numbers.
- Webhook verification uses the raw body and `X-Razorpay-Signature` before parsing trusted fields.
- Duplicate delivery is expected. `x-razorpay-event-id` is stored uniquely and handlers are idempotent.
- Event order is not trusted. The current local/provider state is reconciled before transitions.
- Logs exclude secrets, checkout signatures, full webhook bodies and sensitive payment-method details.

## Failure behaviour

- An uncertain Razorpay Order creation persists the intent and leaves payment under review. Never automatically repeat the create; authenticated exact-receipt recovery must resolve one order or the owner investigates.
- Checkout cancellation or payment failure leaves the order unpaid and permits a bounded retry.
- Invalid signature, unknown order, amount/currency mismatch, duplicate provider payment, or impossible state fails closed and creates an owner-visible alert.
- A delayed webhook leaves the order `PAYMENT_PROCESSING`; an authenticated API fetch may reconcile a time-sensitive buyer view.
- Provider outage does not bypass payment. The owner may explicitly issue the manual fallback or keep the order pending.
- Refund initiation and provider outcome are separate audited states. A refund request does not rewrite the original captured payment.

## Consequences

Benefits:

- Faster buyer confirmation and automatic queue entry after trustworthy captured evidence.
- Less manual UTR/screenshot handling and lower evidence-retention burden.
- Provider-supported UPI Intent/QR plus other enabled checkout methods.
- Better reconciliation, duplicate handling and payment auditability.

Costs and dependencies:

- Merchant onboarding/KYC, live credentials, HTTPS and a public webhook endpoint become launch dependencies.
- Provider fees, settlement timing, enabled methods and refund/cancellation terms must be approved by the owner and must not be invented in code or documentation.
- The system must monitor webhook delay/failure and provide reconciliation tooling.
- Razorpay is a third-party availability and vendor dependency, so manual fallback and operational runbooks remain necessary.

## Implementation boundary

This ADR approves the contract and plan. It does not authorize storing live credentials in the repository or enabling live payments before merchant onboarding, owner-approved policies, staging tests and release gates pass.

October 11 implementation clarification: authenticated reconciliation may confirm an exact current
capture when webhook delivery is delayed/lost. Its persisted `api` evidence/timestamp is distinct
from signed `webhook` evidence, and both enter the same capture transaction. Integration code is
disabled by default and verified with fictional provider responses only. Refunds/manual-UPI are
still unimplemented; see `../LOCAL_WORKFLOW.md` for remaining gates.

## Primary references

- Razorpay Standard Checkout: https://razorpay.com/docs/developer-tools/integrations/standard-checkout/
- Razorpay webhook validation and idempotency: https://razorpay.com/docs/webhooks/validate-test/
- Razorpay UPI methods: https://razorpay.com/docs/payments/payment-methods/upi/
