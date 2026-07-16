# ADR 0004: Private Model Upload Intake

- Status: Accepted
- Date: 2026-07-17
- Owner: Codex root

## Context

Verified buyers need to create quote requests and upload up to five untrusted model files.
The API must not proxy 100 MB bodies or expose permanent storage credentials. Upload intake
must establish ownership and immutable evidence without treating buyer-supplied metadata as
validated geometry.

## Storage decision

- Use an S3-compatible private object-storage adapter. Development targets MinIO; production
  may use a managed S3-compatible service without changing the application contract.
- The API issues a ten-minute SigV4 presigned POST with an exact server-generated object key,
  exact declared size, exact content type, and asset/checksum-claim metadata.
- Object keys contain only server UUIDs under a private original-model prefix. Buyer filenames
  are display metadata and never form a path.
- Storage credentials remain server-side. Buckets are private, deny public access, use default
  encryption and lifecycle policy in deployment, and require explicit browser CORS origins.
- Completion performs a storage HEAD check for actual size and signed metadata. A buyer SHA-256
  claim is not trusted as a verified digest. The asset stays quarantined until an isolated worker
  downloads and independently hashes and parses it.

## Quote-request decision

- A buyer creates a draft request using a per-buyer idempotency token.
- A draft may contain at most five non-rejected assets. Each upload intent has its own
  idempotency token and is immutable once issued.
- Accepted source extensions are STL, 3MF, OBJ, STEP, and STP. Extension and browser MIME checks
  are only early rejection; worker signature/structure validation remains authoritative.
- An upload starts `pending_upload`, becomes `quarantined` only after storage completion checks,
  and later becomes `validating`, `validated`, or `rejected` in the worker phase.
- Submitting a draft requires at least one quarantined asset and no pending uploads. Submission
  moves it to `analyzing`; later worker completion moves it to `estimate_ready` or
  `analysis_failed` and then owner review.
- Buyers can list/read only their own requests. The singleton owner can list/read all requests.
  Cross-buyer identifiers return not found and never reveal resource existence.

## HTTP decision

- Cookie-authenticated mutations require exact trusted origin and session-bound CSRF.
- Upload issuance is rate-limited by client and buyer identifiers.
- Private responses and presigned material use `Cache-Control: no-store`.
- Ordinary quote responses never expose object keys, storage credentials, or permanent URLs.
- Upload errors are fail-closed. Metadata mismatch rejects and deletes the uploaded object when
  deletion is available; it never advances the asset into analysis.

## Consequences

- The browser computes SHA-256 before requesting an upload, but only the future isolated worker
  may promote that claim to `verified_sha256`.
- S3-compatible POST policies provide server-enforced expiry, exact keys/metadata, and a content
  length condition. Deployment still owns bucket privacy, encryption, CORS, and lifecycle.
- Pricing inputs and printer access do not block secure upload intake. They continue to block
  production estimates and printer automation.
