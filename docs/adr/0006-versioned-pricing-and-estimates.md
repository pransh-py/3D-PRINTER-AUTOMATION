# ADR 0006: Versioned Pricing and Immutable Estimates

- Status: Accepted
- Date: 2026-07-17
- Owner: Codex root

## Context

The business has not yet supplied approved filament costs, machine rate, setup/labour charge,
minimum order, contingency, GST treatment, or estimate lifetime. The system therefore cannot
ship a trustworthy default rate card. It can still establish the calculation contract and a
safe owner-controlled configuration path without fabricating those values.

An estimate is financial evidence but is not yet the owner's final quotation. It must be
reproducible from an exact successful slice, survive later rate changes unchanged, and never use
browser-provided totals or floating-point money.

## Rate-card decision

- A pricing policy is a complete immutable-content version. It contains INR machine rate, setup
  fee, minimum order, contingency, tax treatment, estimate lifetime, and at least one material
  rate. There is no update or delete endpoint; a correction creates a new draft version.
- Policy creation is owner-only and CSRF/origin protected. Activation additionally requires
  recent MFA. The database enforces at most one active version, and activation retires the prior
  active version in the same transaction.
- The application seeds no business rates. Draft values have no effect until the owner explicitly
  activates the version. Zero is a valid explicit component because the owner's eventual GST or
  fee decision may be that it does not apply; it is not interpreted as legal advice.
- Material codes are stable machine-facing identifiers. Display names and rates are snapshotted
  into each estimate so later catalog changes cannot rewrite history.
- AD5X machine/process/filament profile files are analysis inputs, not price inputs. Their exact
  digest, slicer version, and material code remain on the referenced successful analysis run. An
  estimate is blocked unless every quote asset has successful sliced filament and duration
  metrics and the selected rate-card material matches the sliced filament profile.

## Calculation decision

Calculation version `pricing-v1` uses only non-negative integers:

```text
material_paise = ceil(filament_mg × material_paise_per_gram / 1,000)
machine_paise = ceil(duration_seconds × machine_paise_per_hour / 3,600)
subtotal_paise = material_paise + machine_paise + setup_paise
contingency_paise = ceil(subtotal_paise × contingency_bps / 10,000)
before_tax_paise = max(subtotal_paise + contingency_paise, minimum_order_paise)
tax_paise = ceil(before_tax_paise × tax_bps / 10,000)
total_paise = before_tax_paise + tax_paise
```

Each fractional paise rounds upward at its component boundary. Delivery/shipping, finishing,
quantity, owner overrides, and discounts are not silently treated as zero by a final quotation;
they remain later explicit quotation inputs. Stakeholder-approved golden cases are still a launch
gate even though invariant tests cover the arithmetic now.

## Estimate decision

- Only the owner can create an estimate, using the active policy, one selected offered material,
  the current quote version, and the exact successful analysis-run ID.
- Each mutation includes a quote-scoped client token. Repeating the same token and inputs returns
  the original estimate; reusing it for different inputs fails. Optimistic quote-version checks
  reject stale owner screens.
- Estimate creation stores measured filament/duration, all selected rates, every component,
  calculation version, policy/material references, creator, creation time, and expiration. It
  advances the quote to `estimate_ready` and increments the quote version transactionally.
- Estimates are append-only through the application. Repricing creates a new snapshot rather than
  editing an earlier result. Buyers see only their own estimate breakdown through the existing
  quote authorization boundary; internal actor IDs and configuration administration remain
  owner-only.
- `estimate_ready` is not acceptance, a payment demand, or a print authorization. Owner
  approve/override/reject, buyer acceptance, delivery charges, and the immutable accepted order
  snapshot remain the next quotation subphase.

## Consequences

- The owner can prepare real rate cards as soon as stakeholder values arrive without a deploy or
  source change, while accidental placeholder pricing remains inactive.
- Historical estimates retain the exact rate and arithmetic evidence after a policy is retired.
- Production quotation accuracy remains blocked until real AD5X profiles produce repeatable slice
  metrics and the owner approves both pricing inputs and golden quote cases.
