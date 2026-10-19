# PrintFlow 3D Canonical Data Model

- Contract version: 1.5
- Status: Authoritative MVP schema contract
- Effective date: 19 October 2026
- Scope: Buyer identity through private model intake, analysis, pricing, quotation, Razorpay payment confirmation with manual-UPI fallback, print execution, QA and fulfillment

This document is the source of truth for database tables, identifiers, relationships, lifecycle states and cross-table invariants. New migrations, ORM models, APIs, tests, ER diagrams and data-flow diagrams must conform to it. A change requires an explicit contract revision and updates to every affected artifact.

The contract distinguishes:

- **Implemented** — base tables in migrations `0001` through `0005`, with the local/manual
  subset in `0006_order_operations`/`0007_analysis_previews` (section 13), payment adapter in
  `0008_payment_adapter` (section 14), delivery in `0009_notifications` (section 15), and
  selected print specifications in `0010_print_specifications` (section 16).
- **Contract-frozen** — approved for the MVP but not yet represented by a migration.

Contract-frozen does not mean optional. It means implementation must follow this document rather than inventing a new shape.

Section 13 is the authoritative implementation projection for the owner-requested local/manual
slice. The fuller table specifications below remain the production target. Optional target fields
and deferred domains are not claimed as implemented. Existing ER/DFD artifacts describe that
full target, not an assertion that all those tables, APIs or external adapters currently exist.

## 1. Global storage conventions

- PostgreSQL is the authoritative production database.
- Every primary key is a UUID named `id`.
- Public APIs expose UUIDs or separate public references; they never expose sequential database identifiers.
- All timestamps are timezone-aware UTC.
- Mutable aggregate roots use `created_at`, `updated_at` and an integer `version` where concurrent owner actions are possible.
- Money is stored as integer paise using `bigint`. Floating-point money is prohibited.
- Filament is stored in milligrams, dimensions in micrometres and durations in seconds.
- Percent-like configuration is stored in basis points where exact calculation matters.
- Enum values are stable lowercase strings enforced by application and database constraints.
- Private object keys are server-generated. User filenames are metadata and never storage paths.
- Hash fields contain lowercase SHA-256 hexadecimal values.
- Accepted quotations, order commercial snapshots, provider payment events, captured attempts, manual-fallback verifications, print authorizations, job events and audit events are immutable evidence.
- Foreign-key deletion is `CASCADE` only for private child records that have no independent business/audit meaning. Evidence and financial/production relationships use `RESTRICT` or `SET NULL`.
- JSON is allowed only for bounded snapshots, structured warnings, provider-neutral details or append-only event payloads. It must not replace a stable relational contract.

## 2. Domain ownership

| Domain | Aggregate roots | Supporting tables |
| --- | --- | --- |
| Identity and access | `users` | `refresh_sessions`, `one_time_tokens`, `mfa_methods`, `mfa_recovery_codes`, `addresses` |
| Model intake and analysis | `quote_requests`, `analysis_runs` | `model_assets`, `print_profiles`, `analysis_asset_results` |
| Pricing and quotation | `pricing_policies`, `quotes` | `material_rates`, `quote_estimates`, `quote_line_items` |
| Orders and payments | `orders`, `payment_intents` | `payment_attempts`, `payment_provider_events`, `manual_upi_beneficiary_versions`, `manual_payment_claims`, `manual_payment_verifications`, `refunds` |
| Production | `print_jobs`, `printers`, `bridge_installations` | `print_job_items`, `print_readiness_checks`, `print_authorizations`, `print_job_events`, `bridge_heartbeats` |
| Fulfillment and messaging | `fulfillments` | `notifications`, `outbox_events` |
| Cross-cutting evidence | `audit_events` | — |

## 3. Identity and access tables

### 3.1 `users` — implemented

One row represents a buyer or the separately provisioned primary owner.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `email` | varchar(320) | no | Unique, normalized identity |
| `display_name` | varchar(100) | no | User-visible name |
| `password_hash` | text | no | Argon2id result; never reversible |
| `role` | enum | no | `buyer` or `owner` |
| `owner_slot` | varchar(16) | yes | Exactly `primary` for the sole owner; null for buyers |
| `status` | enum | no | `pending_verification`, `active`, `disabled` |
| `email_verified_at` | timestamptz | yes | Required before buyer uploads/orders |
| `password_changed_at` | timestamptz | no | Session-revocation boundary |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

Invariant: `(role = owner AND owner_slot = primary) OR (role = buyer AND owner_slot IS NULL)`. The unique owner slot prevents a second active owner record in the MVP.

### 3.2 `refresh_sessions` — implemented

Server-side state for rotating refresh-token families.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `user_id` | UUID | no | FK `users.id`, cascade on user deletion |
| `family_id` | UUID | no | Groups one rotation chain |
| `token_digest` | char(64) | no | Globally unique keyed digest |
| `expires_at`, `authenticated_at` | timestamptz | no | Session validity and recent-auth basis |
| `mfa_authenticated_at` | timestamptz | yes | Owner-sensitive-action basis |
| `rotated_at`, `revoked_at` | timestamptz | yes | Rotation/revocation state |
| `replaced_by_id` | UUID | yes | Self-FK with `SET NULL` |
| `user_agent_digest` | char(64) | yes | Privacy-preserving device hint |
| `created_at` | timestamptz | no | Creation time |

### 3.3 `one_time_tokens` — implemented

Hashed email-verification, password-reset or MFA-login tokens.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `user_id` | UUID | no | FK `users.id`, cascade |
| `purpose` | enum | no | `verify_email`, `reset_password`, `mfa_login` |
| `token_digest` | char(64) | no | Globally unique |
| `expires_at`, `created_at` | timestamptz | no | Token window |
| `consumed_at` | timestamptz | yes | One-time-use proof |

### 3.4 `mfa_methods` — implemented

One TOTP method for the primary owner.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `user_id` | UUID | no | Unique FK `users.id`, cascade |
| `kind` | enum | no | `totp` for MVP |
| `encrypted_secret` | text | no | Application-encrypted |
| `enabled_at` | timestamptz | yes | Null until enrollment completes |
| `last_used_counter` | bigint | yes | Replay prevention |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

### 3.5 `mfa_recovery_codes` — implemented

One row per keyed recovery-code digest.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `mfa_method_id` | UUID | no | FK `mfa_methods.id`, cascade |
| `code_digest` | char(64) | no | Globally unique |
| `created_at` | timestamptz | no | Creation time |
| `used_at` | timestamptz | yes | Null means unused |

### 3.6 `addresses` — contract-frozen

Buyer-owned reusable contact/fulfillment address. Historical fulfillment also records an immutable address snapshot.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `user_id` | UUID | no | FK `users.id`, cascade before business use; otherwise restricted by references |
| `label`, `recipient_name` | varchar | no | Buyer-facing identification |
| `phone_e164` | varchar(20) | no | Normalized phone |
| `line1`, `line2`, `locality`, `district`, `state` | varchar | mixed | Postal address |
| `postal_code` | varchar(12) | no | Indian postal code stored as text |
| `country_code` | char(2) | no | `IN` for MVP |
| `is_default` | boolean | no | At most one default per user |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

## 4. Model intake and analysis tables

### 4.1 `quote_requests` — implemented root; selection fields contract-frozen

One buyer-owned request version containing one to five private models and request-level print/fulfillment selections.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `buyer_id` | UUID | no | FK `users.id`, `RESTRICT` |
| `client_token` | UUID | no | Unique with buyer for idempotent creation |
| `status` | enum | no | See lifecycle states |
| `version` | integer | no | Positive optimistic/request version |
| `material_code`, `color_code`, `quality_preset` | varchar | yes | Required on submission; values must be owner-supported |
| `quantity` | integer | yes | Required on submission and greater than zero |
| `fulfillment_mode` | enum | yes | `pickup`, `local_delivery`, `shipping` |
| `shipping_address_id` | UUID | yes | FK `addresses.id`; required for delivery/shipping |
| `buyer_notes` | text | yes | Sanitized bounded notes |
| `submitted_at` | timestamptz | yes | Set once per submitted version |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

`quote_request.status` values:

```text
draft -> analyzing -> analysis_ready | analysis_failed
analysis_ready -> estimate_ready -> owner_review
owner_review -> quoted | rejected
draft/analysis_failed/analysis_ready/estimate_ready/owner_review -> cancelled
```

### 4.2 `model_assets` — implemented

One private source model within a quote request.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `quote_request_id` | UUID | no | FK `quote_requests.id`, cascade while request is non-commercial |
| `client_token` | UUID | no | Unique with request |
| `original_filename` | varchar(255) | no | Display metadata only |
| `declared_format` | enum | no | `stl`, `3mf`, `obj`, `step` |
| `declared_content_type` | varchar(100) | no | Untrusted hint |
| `expected_size_bytes`, `actual_size_bytes` | bigint | mixed | Positive byte counts |
| `claimed_sha256`, `verified_sha256` | char(64) | mixed | Claimed and server-verified hashes |
| `storage_key` | varchar(512) | no | Unique server-created private key |
| `status` | enum | no | `pending_upload`, `quarantined`, `validating`, `validated`, `rejected` |
| `upload_expires_at`, `uploaded_at` | timestamptz | mixed | Upload timing |
| `rejection_code`, `storage_etag` | varchar/text | yes | Structured failure/storage evidence |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

### 4.3 `print_profiles` — contract-frozen

Versioned owner-approved slicing profile for the AD5X.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `code`, `version` | varchar/integer | no | Unique pair |
| `status` | enum | no | `draft`, `active`, `retired` |
| `printer_model` | varchar(64) | no | `FlashForge AD5X` contract identity; firmware is not assumed |
| `nozzle_diameter_um`, `layer_height_um`, `infill_percent` | integer | no | Positive bounded profile facts |
| `support_mode`, `material_code` | varchar | no | Approved profile selections |
| `slicer_name`, `slicer_version` | varchar | no | Reproducibility evidence |
| `profile_storage_key`, `profile_sha256` | varchar | no | Private immutable profile artifact |
| `created_by_user_id`, `activated_by_user_id` | UUID | mixed | Owner FKs |
| `activated_at`, `created_at`, `updated_at` | timestamptz | mixed | Lifecycle timestamps |

Only one active version per `code` is permitted. Production activation waits for owner-exported and hardware-tested profile evidence.

### 4.4 `analysis_runs` — implemented root; profile FK contract-frozen

One immutable-input analysis attempt for one quote-request version.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `quote_request_id` | UUID | no | FK `quote_requests.id`, cascade |
| `request_version` | integer | no | Unique with request |
| `status` | enum | no | `queued`, `running`, `awaiting_profile`, `succeeded`, `failed` |
| `attempt_count`, `lease_token`, `lease_expires_at` | mixed | mixed | Fenced worker lease |
| `validator_version` | varchar(64) | no | Validation implementation |
| `print_profile_id` | UUID | yes | FK `print_profiles.id`; required once profile is approved |
| `slicer_name`, `slicer_version`, `profile_sha256`, `material_code` | varchar | mixed | Immutable execution evidence |
| `queued_at`, `started_at`, `completed_at` | timestamptz | mixed | Lifecycle timestamps |
| `failure_code` | varchar(64) | yes | Structured buyer-safe mapping |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

### 4.5 `analysis_asset_results` — implemented

Resolves the many-to-many relationship between an analysis run and its model assets and stores per-asset results.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `analysis_run_id` | UUID | no | FK `analysis_runs.id`, cascade |
| `model_asset_id` | UUID | no | FK `model_assets.id`, `RESTRICT` |
| `status`, `detected_format` | enum | mixed | Validation/slicing result |
| `verified_sha256` | char(64) | yes | Input identity |
| `dimension_x_um`, `dimension_y_um`, `dimension_z_um` | bigint | yes | Non-negative geometry |
| `triangle_count`, `object_count`, `fits_build_volume` | mixed | yes | Bounded analysis |
| `warning_codes` | JSON array | no | Structured reviewed codes |
| `filament_mg`, `duration_seconds` | bigint | yes | Non-negative slicer metrics |
| `artifact_storage_key`, `artifact_sha256` | varchar | yes | Trusted sliced artifact |
| `failure_code` | varchar(64) | yes | Structured failure |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

Unique constraint: `(analysis_run_id, model_asset_id)`.

## 5. Pricing and quotation tables

### 5.1 `pricing_policies` — implemented

Immutable-content owner rate-card version.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `version` | integer | no | Globally unique positive version |
| `status` | enum | no | `draft`, `active`, `retired`; at most one active |
| `currency` | char(3) | no | `INR` |
| `machine_rate_paise_per_hour` | bigint | no | Non-negative |
| `setup_fee_paise`, `minimum_order_paise` | bigint | no | Non-negative |
| `contingency_bps`, `tax_bps` | integer | no | Between 0 and 10,000; stakeholder-provided values |
| `estimate_validity_hours` | integer | no | 1–720 |
| `created_by_user_id`, `activated_by_user_id` | UUID | mixed | Owner FKs |
| `activated_at`, `created_at`, `updated_at` | timestamptz | mixed | Lifecycle timestamps |

No default production values are implied by this schema.

### 5.2 `material_rates` — implemented

One material rate inside one policy version.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `pricing_policy_id` | UUID | no | FK `pricing_policies.id`, cascade |
| `code`, `display_name` | varchar | no | Unique code within policy |
| `rate_paise_per_gram` | bigint | no | Non-negative owner-configured value |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

### 5.3 `quote_estimates` — implemented

Immutable system-calculation snapshot for one successful analysis and pricing version.

The table preserves input identities, material/profile facts, rates, measured units, every calculated component, total paise, calculation version and expiry. Its implemented constraints prohibit negative money/units and enforce INR. It references:

- one `quote_request`;
- one `analysis_run`;
- one `pricing_policy`;
- one `material_rate`;
- one creating owner/system user.

An estimate is evidence, not a buyer-payable final quotation.

### 5.4 `quotes` — contract-frozen

Owner-issued final quotation.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `quote_request_id` | UUID | no | FK `quote_requests.id`, `RESTRICT` |
| `quote_estimate_id` | UUID | no | FK `quote_estimates.id`, `RESTRICT` |
| `version` | integer | no | Unique with request |
| `status` | enum | no | `draft`, `issued`, `accepted`, `rejected`, `expired`, `superseded` |
| `currency` | char(3) | no | `INR` |
| `subtotal_paise`, `adjustment_paise`, `tax_paise`, `fulfillment_paise`, `total_paise` | bigint | no | Exact signed/unsigned components; total must reconcile |
| `owner_id` | UUID | no | FK `users.id`, owner role |
| `owner_reason` | text | yes | Required for override or rejection |
| `issued_at`, `expires_at`, `accepted_at` | timestamptz | mixed | Lifecycle timestamps |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

Only an `issued`, unexpired quote may be accepted. Acceptance is single-effect and creates one order.

### 5.5 `quote_line_items` — contract-frozen

Immutable line-item breakdown for a final quote.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `quote_id` | UUID | no | FK `quotes.id`, cascade before issue; immutable after issue |
| `position` | integer | no | Unique positive order within quote |
| `kind` | enum | no | Material, machine, setup, finishing, complexity, contingency, minimum adjustment, tax, fulfillment or owner adjustment |
| `description` | varchar(200) | no | Buyer-visible reviewed text |
| `quantity_milliunits`, `unit_amount_paise`, `amount_paise` | bigint | mixed | Exact calculation representation |
| `source_ref` | JSON | yes | Bounded immutable reference to input evidence |
| `created_at` | timestamptz | no | Creation time |

## 6. Order and payment tables

### 6.1 `orders` — contract-frozen

Immutable commercial snapshot plus server-controlled fulfillment lifecycle.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `public_reference` | varchar(32) | no | Unique buyer/payment reference |
| `buyer_id` | UUID | no | FK `users.id`, `RESTRICT` |
| `accepted_quote_id` | UUID | no | Unique FK `quotes.id`, `RESTRICT` |
| `status` | enum | no | Server-controlled order state |
| `version` | integer | no | Optimistic concurrency |
| `currency` | char(3) | no | `INR` |
| `amount_paise` | bigint | no | Exact accepted quote total |
| `commercial_snapshot` | JSON | no | Bounded immutable quote/rate/profile/fulfillment snapshot |
| `accepted_at` | timestamptz | no | Order creation |
| `cancelled_at`, `completed_at` | timestamptz | yes | Terminal timestamps |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

Order states:

```text
payment_pending -> payment_processing -> paid_confirmed | payment_failed | payment_review
payment_review -> paid_confirmed | payment_rejected
paid_confirmed -> queued -> preparing -> ready_to_print -> printing -> qa
qa -> ready_for_pickup | out_for_delivery | shipped -> completed

Controlled exception states:
on_hold, print_failed, cancelled, refund_pending, refunded
```

### 6.2 `payment_intents` — contract-frozen

One exact payable instruction for one order and provider. The normal provider is `razorpay`; `manual_upi` is an owner-issued fallback.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `order_id` | UUID | no | FK `orders.id`, `RESTRICT` |
| `version` | integer | no | Unique with order |
| `provider` | enum | no | `razorpay` or `manual_upi` |
| `status` | enum | no | `created`, `checkout_pending`, `authorized`, `captured`, `failed`, `review`, `rejected`, `expired`, `cancelled` |
| `currency`, `amount_paise` | char(3)/bigint | no | Exact accepted-order amount; `INR` |
| `payment_reference` | varchar(64) | no | Globally unique local receipt/reference |
| `provider_order_id` | varchar(100) | yes | Globally unique Razorpay Order ID; required only for `razorpay` |
| `manual_beneficiary_version_id` | UUID | yes | FK `manual_upi_beneficiary_versions.id`, required only for `manual_upi` |
| `expires_at`, `created_at`, `updated_at` | timestamptz | mixed | Lifecycle timestamps |

Provider-specific columns are mutually exclusive. The server creates `provider_order_id`; no browser-supplied value may establish the binding.

### 6.3 `payment_attempts` — contract-frozen

Normalized provider payment attempts. One intent may have multiple failed/abandoned attempts but at most one captured business effect.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `payment_intent_id` | UUID | no | FK `payment_intents.id`, `RESTRICT` |
| `provider_payment_id` | varchar(100) | no | Globally unique Razorpay Payment ID |
| `status` | enum | no | `created`, `authorized`, `captured`, `failed`, `partially_refunded`, `refunded` |
| `currency`, `amount_paise` | char(3)/bigint | no | Must equal the intent before capture |
| `method_category` | varchar(40) | yes | Bounded category such as `upi`, `card` or `netbanking`; no account/card secret |
| `provider_status_at` | timestamptz | yes | Provider event/API observation time |
| `authorized_at`, `captured_at`, `failed_at` | timestamptz | yes | Normalized lifecycle timestamps |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

### 6.4 `payment_provider_events` — contract-frozen

Append-only Razorpay webhook evidence and processing state.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `provider` | enum | no | `razorpay` |
| `provider_event_id` | varchar(120) | no | Unique with provider; source is `x-razorpay-event-id` |
| `event_type` | varchar(80) | no | Reviewed allowlisted provider event name |
| `payload_sha256` | char(64) | no | Hash of exact raw request body |
| `signature_validated_at` | timestamptz | no | Set only after raw-body HMAC succeeds |
| `payment_intent_id`, `payment_attempt_id` | UUID | yes | Correlated restricted FKs when known |
| `provider_created_at` | timestamptz | yes | Provider-reported event time |
| `status` | enum | no | `received`, `processed`, `ignored`, `failed` |
| `failure_code` | varchar(80) | yes | Bounded non-secret failure classification |
| `received_at`, `processed_at` | timestamptz | mixed | Delivery and processing times |

Webhook signatures and full raw payloads are not stored in logs. Any retained encrypted payload follows the approved financial-data retention policy.

### 6.5 `manual_upi_beneficiary_versions` — contract-frozen

Versioned owner-approved fallback UPI destination; historical intents never point at mutable live configuration.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `version` | integer | no | Globally unique |
| `status` | enum | no | `draft`, `active`, `retired`; at most one active |
| `vpa_ciphertext` | text | no | Encrypted configuration |
| `beneficiary_display_name` | varchar(120) | no | Buyer-visible only after owner issues fallback |
| `qr_payload_template` | text | yes | Owner-approved template; no secret |
| `created_by_user_id`, `activated_by_user_id` | UUID | mixed | Owner FKs |
| `activated_at`, `created_at` | timestamptz | mixed | Lifecycle timestamps |

### 6.6 `manual_payment_claims` — contract-frozen

Buyer-submitted fallback claim; never proof of payment.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `payment_intent_id` | UUID | no | FK `payment_intents.id`; intent provider must be `manual_upi` |
| `submitted_by_user_id` | UUID | no | Must own the order |
| `status` | enum | no | `submitted`, `under_review`, `verified`, `rejected` |
| `utr_reference_normalized` | varchar(100) | no | Globally unique normalized reference |
| `claimed_amount_paise` | bigint | no | Buyer claim only |
| `evidence_storage_key`, `evidence_sha256` | varchar | yes | Private scanned evidence |
| `submitted_at`, `created_at`, `updated_at` | timestamptz | no | Lifecycle timestamps |

### 6.7 `manual_payment_verifications` — contract-frozen

One immutable owner decision for one fallback claim.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `manual_payment_claim_id` | UUID | no | Unique FK `manual_payment_claims.id`, `RESTRICT` |
| `verifier_user_id` | UUID | no | Owner with recent MFA authentication |
| `decision` | enum | no | `verified` or `rejected` |
| `observed_amount_paise` | bigint | yes | Required when verified |
| `beneficiary_matched`, `reference_matched`, `settled_state_confirmed` | boolean | no | Actual-account checklist |
| `reason` | text | yes | Required for rejection or exception |
| `verified_at`, `created_at` | timestamptz | no | Immutable decision timestamps |

Gateway capture and fallback verification both call the same idempotent confirmation transaction: update intent/order, append audit evidence and create exactly one print-job outbox event.

### 6.8 `refunds` — contract-frozen

Owner-initiated refund intent plus provider/manual reconciliation evidence.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `order_id`, `payment_intent_id` | UUID | no | Restricted FKs |
| `payment_attempt_id` | UUID | yes | Captured provider attempt for Razorpay refunds |
| `provider_refund_id` | varchar(100) | yes | Unique provider ID when Razorpay handles the refund |
| `initiated_by_user_id` | UUID | no | Owner with recent MFA |
| `status` | enum | no | `pending`, `processed`, `failed`, `cancelled` |
| `amount_paise` | bigint | no | Positive, not above captured amount minus prior processed refunds |
| `manual_external_reference`, `reason` | varchar/text | mixed | Manual reference only for fallback; reason always required |
| `initiated_at`, `processed_at` | timestamptz | mixed | Lifecycle |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

## 7. Production tables

### 7.1 `printers` — contract-frozen

Registered physical printer. The MVP permits one active FlashForge AD5X.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `code`, `display_name` | varchar | no | Unique operational identity |
| `model` | varchar(64) | no | FlashForge AD5X |
| `firmware_version` | varchar(64) | yes | Observed, never assumed |
| `state` | enum | no | `unknown`, `offline`, `idle`, `busy`, `paused`, `error`, `maintenance` |
| `active_job_id` | UUID | yes | FK `print_jobs.id` added after both tables exist |
| `last_seen_at`, `created_at`, `updated_at` | timestamptz | mixed | Operational timestamps |

### 7.2 `bridge_installations` — contract-frozen

One paired Windows bridge installation.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `printer_id` | UUID | no | Unique FK `printers.id`, `RESTRICT` |
| `status` | enum | no | `pending_pairing`, `active`, `offline`, `revoked` |
| `installation_name`, `bridge_version`, `adapter_name` | varchar | no | Operational identity |
| `credential_digest` | char(64) | no | Rotatable installation credential digest |
| `paired_by_user_id` | UUID | no | Owner FK |
| `paired_at`, `last_heartbeat_at`, `revoked_at` | timestamptz | mixed | Lifecycle |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

### 7.3 `bridge_heartbeats` — contract-frozen

Bounded operational history used for health, reconciliation and incident review.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `bridge_installation_id`, `printer_id` | UUID | no | Restricted FKs |
| `observed_at` | timestamptz | no | Indexed time |
| `bridge_version`, `firmware_version`, `printer_state` | varchar/enum | mixed | Observed facts |
| `active_job_id` | UUID | yes | FK `print_jobs.id`, `SET NULL` |
| `details` | JSON | no | Bounded adapter diagnostics without secrets |

### 7.4 `print_jobs` — contract-frozen

Queueable production attempt. An order may have multiple jobs for multiple parts or authorized reprints.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `order_id` | UUID | no | FK `orders.id`, `RESTRICT` |
| `sequence` | integer | no | Unique positive sequence per order |
| `status` | enum | no | Queue/production lifecycle |
| `queue_rank` | bigint | yes | Owner-controlled ordering while queued |
| `printer_id` | UUID | yes | FK `printers.id`, `RESTRICT` when assigned |
| `attempt_number` | integer | no | Positive |
| `failure_code`, `owner_note` | varchar/text | yes | Structured/operator evidence |
| `queued_at`, `started_at`, `completed_at` | timestamptz | mixed | Lifecycle |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

Print-job states:

```text
queued, on_hold, preparing, ready_to_print, authorized,
claimed, printing, qa, completed, failed, cancelled
```

### 7.5 `print_job_items` — contract-frozen

Manifest linking a print job to trusted sliced outputs.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `print_job_id` | UUID | no | FK `print_jobs.id`, cascade before execution |
| `analysis_asset_result_id` | UUID | no | FK `analysis_asset_results.id`, `RESTRICT` |
| `quantity` | integer | no | Positive |
| `artifact_storage_key`, `artifact_sha256` | varchar | no | Immutable approved artifact |
| `position` | integer | no | Unique within job |
| `created_at` | timestamptz | no | Creation time |

### 7.6 `print_readiness_checks` — contract-frozen

Owner acknowledgement before an authorization is issued.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `print_job_id`, `printer_id` | UUID | no | Restricted FKs |
| `completed_by_user_id` | UUID | no | Owner |
| `checklist_version` | varchar(32) | no | Reviewed checklist identity |
| `checklist_snapshot` | JSON | no | Bed/material/nozzle/area/readiness confirmations |
| `completed_at` | timestamptz | no | Recent-auth controlled time |
| `created_at` | timestamptz | no | Immutable creation |

### 7.7 `print_authorizations` — contract-frozen

Short-lived single-use authorization binding a job, printer, bridge and exact manifest.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `print_job_id`, `printer_id`, `bridge_installation_id`, `readiness_check_id` | UUID | no | Restricted FKs |
| `nonce_digest` | char(64) | no | Globally unique |
| `manifest_sha256` | char(64) | no | Hash of job-item manifest |
| `issued_by_user_id` | UUID | no | Owner |
| `issued_at`, `expires_at` | timestamptz | no | Short validity window |
| `claimed_at`, `consumed_at`, `revoked_at` | timestamptz | yes | Single-use lifecycle |
| `result_code` | varchar(64) | yes | Idempotent outcome |

At most one live authorization exists per job. A claimed/consumed nonce cannot be reused.

### 7.8 `print_job_events` — contract-frozen

Append-only normalized production event stream.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `print_job_id`, `printer_id`, `bridge_installation_id` | UUID | no | Restricted FKs |
| `event_type` | varchar(64) | no | Reviewed normalized event |
| `source_event_id` | varchar(128) | no | Unique with bridge for deduplication |
| `progress_bps` | integer | yes | 0–10,000 |
| `observed_at`, `received_at` | timestamptz | no | Device/server timing |
| `details` | JSON | no | Bounded non-secret diagnostics |

## 8. Fulfillment and messaging tables

### 8.1 `fulfillments` — contract-frozen

One fulfillment record per order.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `order_id` | UUID | no | Unique FK `orders.id`, `RESTRICT` |
| `mode` | enum | no | `pickup`, `local_delivery`, `shipping` |
| `status` | enum | no | `pending`, `ready_for_pickup`, `out_for_delivery`, `shipped`, `delivered`, `completed`, `failed`, `returned` |
| `source_address_id` | UUID | yes | FK `addresses.id`, `SET NULL` |
| `address_snapshot` | JSON | yes | Immutable destination at dispatch |
| `carrier_name`, `tracking_reference` | varchar | yes | Manual fulfillment evidence |
| `charge_paise` | bigint | no | Must match order commercial snapshot or recorded exception |
| `prepared_by_user_id` | UUID | yes | Owner |
| `dispatched_at`, `delivered_at`, `completed_at` | timestamptz | yes | Lifecycle |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

### 8.2 `notifications` — contract-frozen

User-visible delivery record derived from an outbox event.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `outbox_event_id` | UUID | no | FK `outbox_events.id`, `RESTRICT` |
| `recipient_user_id` | UUID | yes | FK `users.id`, `SET NULL` |
| `channel` | enum | no | `email` for MVP |
| `template_code`, `template_version` | varchar | no | Reviewed content identity |
| `destination_digest` | char(64) | no | Do not persist/log raw destination unnecessarily |
| `status` | enum | no | `pending`, `sent`, `failed`, `dead_lettered` |
| `provider_message_id` | varchar | yes | Provider evidence |
| `attempt_count`, `available_at`, `sent_at`, `last_error_code` | mixed | mixed | Retry state |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

### 8.3 `outbox_events` — implemented

Transactional event awaiting at-least-once publication.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `topic`, `aggregate_type` | varchar(64) | no | Reviewed routing identity |
| `aggregate_id` | UUID | no | Aggregate reference |
| `idempotency_key` | varchar(128) | no | Globally unique |
| `payload` | JSON | no | Versioned bounded event |
| `available_at`, `published_at` | timestamptz | mixed | Publication state |
| `attempt_count`, `last_error_code` | mixed | mixed | Retry evidence |
| `created_at`, `updated_at` | timestamptz | no | Audit timestamps |

## 9. Cross-cutting evidence

### 9.1 `audit_events` — implemented core; generic target fields contract-frozen

Append-only evidence for authentication, pricing, quotation, payment, production, fulfillment and sensitive data access.

| Column | Type | Null | Contract |
| --- | --- | --- | --- |
| `id` | UUID | no | Primary key |
| `event_type` | varchar(64)/enum | no | Reviewed event name |
| `actor_user_id`, `target_user_id` | UUID | yes | FKs `users.id`, `SET NULL` |
| `target_type`, `target_id` | varchar/UUID | yes | Generic business target |
| `session_id`, `request_id` | UUID/varchar | yes | Correlation evidence |
| `before_ref`, `after_ref` | JSON | yes | Bounded immutable references, not secret payloads |
| `details` | JSON | no | Bounded non-secret metadata |
| `occurred_at` | timestamptz | no | Indexed event time |

Application roles must be unable to update or delete audit events.

## 10. Canonical relationships and cardinalities

| Parent | Relationship | Child | Cardinality |
| --- | --- | --- | --- |
| `users` | owns | `addresses` | 1:N |
| `users` | creates | `quote_requests` | 1:N |
| `quote_requests` | contains | `model_assets` | 1:1..5 |
| `quote_requests` | schedules | `analysis_runs` | 1:N |
| `analysis_runs` | evaluates through | `analysis_asset_results` | 1:N |
| `model_assets` | appears in | `analysis_asset_results` | 1:N |
| `print_profiles` | is used by | `analysis_runs` | 1:N |
| `pricing_policies` | defines | `material_rates` | 1:N |
| `analysis_runs` | produces | `quote_estimates` | 1:N |
| `pricing_policies` | prices | `quote_estimates` | 1:N |
| `quote_requests` | receives | `quotes` | 1:N |
| `quote_estimates` | supports | `quotes` | 1:N |
| `quotes` | contains | `quote_line_items` | 1:N |
| `quotes` | is accepted as | `orders` | 1:0..1 |
| `orders` | has versions of | `payment_intents` | 1:N |
| `payment_intents` | receives | `payment_attempts` | 1:N |
| `payment_intents` | correlates | `payment_provider_events` | 1:N |
| `payment_intents` | may receive fallback | `manual_payment_claims` | 1:N only for `manual_upi` |
| `manual_payment_claims` | is decided by | `manual_payment_verifications` | 1:0..1 |
| `orders` | may have | `refunds` | 1:N |
| `orders` | produces | `print_jobs` | 1:N |
| `print_jobs` | contains | `print_job_items` | 1:N |
| `analysis_asset_results` | supplies | `print_job_items` | 1:N |
| `print_jobs` | has | `print_readiness_checks` | 1:N |
| `print_jobs` | has | `print_authorizations` | 1:N over time, at most one live |
| `printers` | receives | `print_jobs` | 1:N |
| `bridge_installations` | controls | `printers` | 1:1 in MVP |
| `bridge_installations` | emits | `bridge_heartbeats` | 1:N |
| `print_jobs` | emits | `print_job_events` | 1:N |
| `orders` | is completed by | `fulfillments` | 1:0..1 |
| `outbox_events` | produces | `notifications` | 1:N |
| `users` | performs | `audit_events` | 1:N |

## 11. Non-negotiable cross-table invariants

1. A buyer can reference only their own quote requests, models, quotes, orders, payments, addresses and fulfillments.
2. A quote request can be submitted only with one to five validated supported models and complete required selections.
3. Analysis and estimates bind immutable request versions, input hashes, profile identity and pricing-policy identity.
4. A final quote cannot be issued without an owner decision and complete reconciled line items.
5. One issued quote creates at most one order. Later policy changes never rewrite quote/order snapshots.
6. Browser checkout state, an unsigned/uncorrelated provider event, `authorized` status, or a manual claim cannot transition an order to paid.
7. A paid transition requires either a persisted captured Razorpay attempt supported by a signature-valid event/reconciliation or a persisted owner verification of an owner-issued manual fallback.
8. Payment confirmation, order transition, audit event and print-job outbox event are one database transaction.
9. An order cannot enter the print queue unless its payment state is `paid_confirmed`.
10. A print authorization requires the authorized next job, matching manifest hashes, a fresh bridge/printer state and a recent owner readiness check.
11. A bridge executes only the job/manifest bound to a live, single-use authorization.
12. Duplicate provider events/payments, fallback claims, outbox deliveries, bridge claims and job events are idempotent and never create duplicate business effects or prints.
13. Fulfillment begins only after successful print QA, except an explicitly audited owner exception.
14. Private objects and payment evidence remain private and follow the owner-approved retention policy.
15. Audit, provider-event and job-event records are append-only and exclude secrets, signatures, full raw webhook bodies, signed URLs and raw private model contents.

## 12. Migration implementation order

The local slice uses `0006_order_operations` for dependency-ordered commercial/payment-evidence,
production and fulfilment tables; `0007_analysis_previews` adds private preview references and
selection/single-printer/bridge-status checks. Both preserve evidence with a forward-fix-only
downgrade policy. They seed no business values or external credentials.

Future migrations must be sliced in this dependency order:

1. `addresses`, `print_profiles` and required extensions to quote/analysis tables.
2. `quotes`, `quote_line_items` and `orders`.
3. `payment_intents`, `payment_attempts`, `payment_provider_events`, `manual_upi_beneficiary_versions`, `manual_payment_claims`, `manual_payment_verifications` and `refunds`.
4. `printers`, `bridge_installations`, `print_jobs` and `print_job_items`.
5. `print_readiness_checks`, `print_authorizations`, `bridge_heartbeats` and `print_job_events`.
6. `fulfillments`, `notifications` and generic audit-target extensions.

Every migration requires upgrade tests, constraint tests, authorization tests and a reviewed downgrade/forward-fix policy. No migration may seed production pricing, material, tax, Razorpay credentials/settings, manual UPI, legal, fulfillment or printer-protocol facts before owner approval.

## 13. Local manual implementation projection

The owner requested local verification, deferred Razorpay and supplied no approved rates, tax,
delivery/refund policy or hardware profiles. This projection makes those boundaries explicit.
`LOCAL_WORKFLOW.md` owns its operational setup and verification evidence.

| Domain | Implemented projection | Still deferred from the full target |
| --- | --- | --- |
| Request selection | `quantity` 1–100, `fulfillment_mode`, optional `buyer_notes` and `owner_rejection_reason` | Saved addresses, selectable database `print_profiles` and broader material/preset selection |
| Analysis | Existing run/results plus optional paired `preview_storage_key`/`preview_sha256`; pinned executable and standalone profile files | Database profile FK, real Orca/AD5X repeatability and production container verification |
| Final quotes | Issued-only immutable commercial rows, positive reconciled INR totals, version uniqueness, one issued/accepted row per request; immutable amount-only line items | Draft quotation editing; optional per-line quantity/unit-price columns |
| Orders | Full accepted commercial snapshot and optimistic lifecycle version | Policy-driven cancellation/refund mutations |
| Payment evidence | Intent, immutable normalized capture, webhook/API validation source, account/order binding, exact-current-state reconciliation, Checkout and production outbox | Real merchant/widget/webhook delivery, richer provider attempt history, manual beneficiary/claims and refunds |
| Production | Single `ad5x` logical printer code and atomic `active_job_id` reservation; `print_jobs.version`, FIFO rank, immutable job items/events | Physical state observations, automated dispatch, hardware recovery and policy-driven reprints |
| Bridge | Hashed one-use pairing code/expiry, hashed credential, latest connectivity heartbeat and revocation | `bridge_heartbeats` history, Windows-protected persistence/service installation and printer telemetry |
| Readiness and grants | Manifest hash on readiness; printer nullable for manual compatibility; bound expiring download grant with claimed/consumed/revoked timestamps | Automatic start nonce validation and command reconciliation; the manual adapter issues no printer command |
| Events | Owner event can have no bridge ID; `(print_job_id, source_event_id)` uniqueness | Bridge telemetry/event ordering contracts for a real adapter |
| Fulfilment | Accepted address snapshot, manual carrier/tracking and lifecycle timestamps; transactional generic email, fenced delivery/retry diagnostics | Reusable address FK, courier integration, approved real sender/retention and external inbox delivery |

Local rejection reasons live on the request so rejecting or superseding a quotation never rewrites
its issued commercial reason. ORM snapshot/evidence guards supplement service invariants; they
are not represented as PostgreSQL privilege enforcement. All JSON timestamp responses normalize
SQLite's UTC-naive values to explicit UTC without changing Python datetime inputs.

## 14. Payment adapter implementation contract (11 October 2026)

The full-product request authorizes completing integration code, not activating a merchant
account or inventing business policies. Razorpay remains disabled by default. Test and live
keys are never interchangeable, and live activation still requires the release gates in
`ROADMAP.md`. Refunds and manual-UPI instructions remain unavailable without approved policy
and beneficiary facts.

- One Razorpay intent (version 1) per accepted order. Its receipt is `pf_` plus its UUID hex.
  Persist the intent **before** the external create request; concurrent requests reuse it.
  Never automatically repeat an uncertain create. Recover by authenticated receipt search;
  zero or multiple exact matches require owner investigation, not a new payable instruction.
- Add `provider_key_id`, `checkout_payment_id`, `last_reconciled_at` and bounded `failure_code`
  to intents. The first is a public credential identity, not a secret. The checkout payment ID
  is an authenticated callback hint, never capture evidence. Bound amount/currency/receipt/
  provider order/account identity cannot be rewritten.
- Provider events gain `evidence_source` (`webhook` default or `api`), nullable
  `api_authenticated_at`, and nullable `signature_validated_at`. A database constraint requires
  exactly the corresponding validation timestamp. API observations use a locally generated
  `api_` event ID and `api.reconciled` type; they never pretend to be signed webhooks.
  Only bounded normalized order/payment fields are hashed for API evidence; full responses
  containing card/contact/UPI details are neither persisted nor logged. Immutable evidence
  fields are distinct from mutable processing/correlation fields.
- `POST /orders/{id}/checkout` uses authenticated buyer ownership, verification, CSRF and
  trusted origin; it accepts no commercial input. Returns public key ID, stored provider
  order ID, approved Checkout display name, accepted INR amount, intent ID and test-mode marker.
- `POST /orders/{id}/checkout-return` checks the stored provider Order ID plus payment ID
  HMAC. It records processing feedback only, never paid/outbox/production.
- `POST /orders/{id}/reconcile` fetches the stored provider order and its payments using
  server credentials. Buyer ownership or recent-MFA owner is required. Current exact paid
  order plus captured, unrefunded matching payment is authoritative API evidence.
- `POST /payments/razorpay/webhook` validates bounded exact raw bytes before JSON parsing,
  requires a bounded provider event ID, and deduplicates by ID **and body hash**. Subscribed
  events are `payment.captured`, `order.paid`, `payment.authorized`, `payment.failed`.
  Non-capture events do not regress a paid order. Capture events additionally fetch current
  provider order/payment state; stale captures after refunds cannot enqueue work.
- The existing capture transaction remains the only payment-to-production boundary. Both
  signed webhook and authenticated API evidence use the same exact-match, deduplicated,
  atomic order/attempt/audit/outbox transaction. Invalid, unknown, mismatched or authorized
  observations create no production effect. Provider outages leave durable retryable evidence.
- The worker reconciles unresolved intents in bounded, throttled batches. HTTP owner/buyer
  reconciliation shares the same checks. No adapter invokes payment capture/refund itself.

Migration `0008_payment_adapter` implements these additions without seeding credentials,
rates or merchant facts. The API UI exposes availability and test mode, but never gateway
secrets, raw signatures, private payloads or a client-accessible “mark paid” action.

## 15. Transactional notification implementation contract

Workflow email is disabled by default until the owner approves sender, public URL and privacy
operations. It reuses the existing SMTP boundary; it does not add marketing, SMS, tracking or
another contact-data store. Identity verification/reset email is independent of this flag.

- Quote issuance/rejection, acceptance, confirmed payment, production changes and fulfillment
  create `notification.requested` outbox records in the same transaction as the business event.
  Intake submission and terminal analysis create owner alerts. Each payload contains only
  schema version, recipient UUID and a reviewed template code. No email, notes, address,
  model name, payment details, object key or signed URL is copied to the payload.
- Implement `notifications` as specified in section 8.2. `(outbox_event_id,
  recipient_user_id, template_code)` is unique. Add paired nullable `lease_token` and
  `lease_expires_at` for fenced, bounded delivery/recovery. Channel is email; version is `1`.
- Resolve only an active, verified recipient with the template's expected role. Store a
  purpose-separated HMAC destination digest, not the raw email. A changed destination is
  dead-lettered rather than redirected automatically. Templates contain factual, generic
  notices and a configured HTTPS/sign-in screen link, not private order information.
- Publication and notification creation are atomic. Delivery claims use database CAS,
  commit before SMTP, and acknowledge only their lease token. Retries are bounded and
  delayed; failed submissions never roll back or authorize a commercial/printing transition.
  A process crash after SMTP acceptance can produce duplicate email: SMTP is at-least-once,
  not exactly-once. A stable Message-ID identifies the submission but cannot guarantee remote
  deduplication. `sent` means SMTP accepted it, not inbox delivery.
- Owner-only list shows status, template, attempt count and sanitized error code, never raw
  recipients or provider exceptions. Recent-MFA, CSRF-protected retry of a dead letter is
  audited and compare-and-set; it cannot alter recipient or message identity.
- Migration `0009_notifications` seeds no contact, sender, policy or business facts. Production
  activation and retention remain owner decisions; lab demonstrations send fictional contacts
  only to a loopback SMTP sink.

## 16. Selected print specifications and local storage

Migration `0011_system_estimates` permits a nullable `quote_estimates.created_by_user_id` for an
automatic first calculation. Its audit actor is null rather than impersonating the owner. The
worker recovers successful, preset-bound `analysis_ready` requests from persisted state using a
deterministic calculation token. Request locking/version checks protect against concurrent owner
actions. A system pass cannot refresh, supersede or issue a quotation; manual recalculation and
recent-MFA final quotation retain their existing boundaries.

Migration `0012_model_review_audit` extends the audit-event allowlist with
`quote.model_source_accessed`. The owner-only source-review route binds request and asset,
requires validated status and an established hash, verifies downloaded bytes and records only
actor/request/asset IDs. It never serves private object keys or unvalidated quarantine files.

Migration `0010_print_specifications` adds nullable JSON `print_specification` to
`quote_requests` and `quotes`, and nullable varchar(32) `print_preset_code` to `analysis_runs`.
These are the implemented selection projection, replacing the deferred individual selection
columns for this local delivery. Existing rows remain null and retain legacy behavior.

The bounded specification contains preset code/label, material code, profile hash, selected
colour and profile-derived nozzle, layer height, infill, supports, walls and filament type.
It never contains local paths. Client tokens cannot be reused with a different specification.
The worker resolves the captured preset/hash rather than silently using a global profile.
Sliced evidence must match that code, hash and material before it can be quoted. The issued
quote copies the specification; the accepted commercial snapshot schema version 2 copies it
again. Version 1 orders remain readable and have no invented specification. Issued/accepted
snapshot immutability follows the existing ORM protection and production-role caveats.

The preset manifest is deployment configuration, not a fabricated `print_profiles` SQL table.
Its entries become buyer-visible only when verified and priced by the active rate card.
The owner confirmed an AD5X and single-machine private local storage on 19 October. Local
bytes remain outside the web/public tree and are addressed internally by hashed object keys.
The authenticated, CSRF-protected PUT body is bounded by the existing upload intent's owner,
expiry, exact size and digest. The source is still quarantined and validated by the worker.
No new paid-state or printer-command authority is granted by this storage adapter. It is
rejected in staging/production and does not claim S3 durability, encryption or versioning.
