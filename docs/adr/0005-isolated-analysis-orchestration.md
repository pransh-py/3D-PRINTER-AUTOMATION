# ADR 0005: Isolated Analysis Orchestration

- Status: Accepted
- Date: 2026-07-17
- Owner: Codex root

## Context

Submitting a quote currently freezes quarantined uploads and moves the request to `analyzing`,
but no durable job or worker consumes that state. Uploaded STL, 3MF, OBJ, and STEP files are
untrusted. Parser and slicer crashes, excessive resource use, archive traversal, profile drift,
and duplicate job delivery must not corrupt quote state or expose production credentials.

The AD5X has an official 220 x 220 x 220 mm build volume and FlashForge documents
Orca-Flashforge as its supported slicing workflow. A trustworthy production estimate still
requires the business's exported AD5X machine, process, and filament profiles plus representative
hardware comparisons. Until those inputs exist, the system may report validation evidence but
must not invent filament, duration, price, or printability results.

## Durable job decision

- PostgreSQL is the workflow authority. Quote submission atomically creates one immutable
  `analysis_run` for the submitted quote version and one transactional outbox event.
- A dispatcher publishes outbox events to a private Redis Stream. Publishing is at least once;
  the outbox event ID and analysis-run ID are stable idempotency keys.
- A worker consumer group claims stream messages. A database lease token and expiry fence
  concurrent or redelivered attempts. Terminal runs are idempotent no-ops and their messages are
  acknowledged.
- Redis loss cannot erase the system-of-record job. Unpublished outbox rows are retried, and
  unacknowledged stream entries are reclaimed after their lease expires.
- One analysis run belongs to exactly one quote version. Re-analysis creates a new quote version
  and run rather than rewriting completed evidence.

## Trust-boundary decision

- The worker orchestrator has least-privilege access to the database, Redis, and only the model
  object prefixes it needs. It streams the original into a fresh per-job scratch directory,
  enforces the configured byte limit, and independently verifies SHA-256 before parsing.
- Parsing and slicing run in a separate low-privilege sandbox process/container. The sandbox gets
  explicit input, output, and approved profile paths only; it receives a scrubbed environment,
  no application/storage/database/Redis credentials, no printer access, and no network.
- The sandbox has CPU, memory, process, file-count, archive-expansion, output-size, and wall-clock
  limits. Production uses a read-only container image, a writable size-limited scratch mount,
  dropped capabilities, `no-new-privileges`, and no network.
- Worker logs and API responses never include model contents, signed URLs, object keys, raw parser
  output, environment values, or unsafe exception text.

## Validation decision

- The independently computed digest must match the buyer claim before an asset can become
  `validated`; a mismatch rejects the asset and fails the run.
- Format detection is content-based. The validator accepts bounded STL, 3MF, OBJ, and STEP source
  structures only. Uploaded G-code, sliced 3MF, nested archives, external OBJ resources, unsafe
  ZIP paths/links, XML external entities, non-finite coordinates, and excessive geometry fail
  closed.
- 3MF archive entry count, per-entry size, total expanded size, compression ratio, relationship
  targets, and XML complexity are bounded before model parsing.
- Geometry evidence uses integer micrometres and integer counts. Build-volume fit compares the
  oriented model bounds with 220,000 micrometres on each AD5X axis, but remains advisory until the
  approved slicer has arranged and sliced the plate.

## Slicing decision

- OrcaSlicer/Orca-Flashforge is invoked only through a versioned adapter with an exact binary
  digest and immutable exported machine, process, and filament profile digests.
- OrcaSlicer 2.3.2 is the minimum upstream version because it includes fixes for a 3MF path
  traversal vulnerability and CLI slicing crashes. Production may use a reviewed newer pin.
- Commands are argument arrays without a shell. Only fixed adapter flags and server-owned profile
  paths are allowed; buyer filenames and metadata never become command options.
- Exit status, timeout, output inventory, artifact hashes, and bounded structured metrics are
  validated independently. Slicer output is evidence, not trusted control input.
- The pipeline may complete safe format validation while no approved profile is configured, but
  it reports `awaiting_profile` and does not create a sliced artifact, printability decision,
  estimate-ready state, or price.

## Public state and result decision

- Analysis runs use `queued`, `running`, `awaiting_profile`, `succeeded`, and `failed`.
- Quote requests gain `analysis_ready` for completed validation/slicing evidence that has not yet
  been priced. `estimate_ready` remains reserved for a reproducible pricing result.
- Asset results record verified digest, detected format, bounded geometry metadata, build-volume
  evidence, warnings from an allowlisted code set, slicer/profile versions, filament milligrams,
  duration seconds, and artifact hashes where available.
- Buyers can read only their own safe result summaries. The owner may additionally read bounded
  diagnostic codes. Raw logs and private object references are never returned by these endpoints.

## Consequences

- The API request path remains free of CPU-heavy parsing and slicing.
- Duplicate publication, worker restart, and lease expiry are normal tested events rather than
  exceptional guesses.
- Real AD5X estimates remain blocked until the owner supplies exported Orca-Flashforge profiles
  and approves representative comparison models. The worker adapter can be tested meanwhile with
  deterministic fake binaries and malicious-format fixtures.

## References

- FlashForge AD5X specifications: https://www.flashforge.com/products/flashforge-ad5x-3d-printer
- FlashForge Orca-Flashforge guide:
  https://wiki.flashforge.com/en/Orca-Flashforge-and-Flashmaker/orca-flashforge-quick-start-guide
- OrcaSlicer 2.3.2 release notes: https://github.com/OrcaSlicer/OrcaSlicer/releases/tag/v2.3.2
