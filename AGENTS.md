# Repository AI Workflow

## Project context

- Project name: `xxx` (temporary working name).
- Purpose: A public 3D-printing storefront and operations platform for a Chennai business. Buyers upload models, receive system-generated estimates, await owner approval, pay by UPI, and track production and fulfillment. The owner manages quotations, verified payments, a single FlashForge AD5X print queue, and pickup/local-delivery/pan-India shipping.
- Production expectations: Safe physical-printer control, trustworthy pricing, private model storage, auditable payment decisions, recoverable operations, and a usable one-week MVP without weakening security boundaries.
- Tech stack: Next.js and TypeScript frontend; FastAPI/Python API; PostgreSQL; Redis-backed jobs; S3-compatible private object storage; isolated OrcaSlicer analysis; a Python Windows print bridge; Docker Compose for development.
- Install commands: `npm --prefix apps/web install`; `python3.13 -m venv .venv313`; `.venv313/bin/pip install -e 'services/api[dev]' -e 'services/worker[dev]'`.
- Test commands: `.venv313/bin/pytest services/api/tests services/worker/tests`; `npm --prefix apps/web run test`.
- Lint commands: `.venv313/bin/ruff check services/api services/worker`; `npm --prefix apps/web run lint`.
- Type-check commands: `.venv313/bin/mypy services/api/src services/worker/src`; `npm --prefix apps/web run typecheck`.
- Development-server commands: `.venv313/bin/uvicorn xxx_api.main:app --app-dir services/api/src --reload --host 127.0.0.1 --port 8000`; `.venv313/bin/xxx-worker`; `npm --prefix apps/web run dev`.
- Architecture and product documents: `docs/PRODUCT_REQUIREMENTS.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, and `docs/ROADMAP.md`.
- Learning contract: Delivery mode. Codex may implement project code; explain architecture, security-sensitive behavior, operational setup, and owner actions clearly. Do not reserve code for the user to type unless they request it.

Do not infer missing pricing, material, tax, shipping, legal, or printer-protocol facts. Codex root must establish them with the owner and update the product documents before implementation that depends on them.

## Source of truth

This file owns durable project and workflow rules. `CLAUDE.md`, Claude agent definitions, and repository skills may add role-specific procedures but must not override this file. Product architecture and public contracts belong in their eventual project documents and must be referenced from here.

Codex root is the only orchestrator. A native Codex subagent is never described or treated as a Sonnet executor. Sonnet work is launched only through the local Claude Code CLI with `claude-sonnet-5` pinned.

## Codex root responsibilities

Codex root exclusively owns:

- Planning, milestones, architecture, public APIs, schemas, public names, dependencies, and cross-component contracts.
- Product and business decisions, legal and security judgment, authentication, authorization, billing, privacy, and data-retention decisions.
- Task decomposition, exact executor briefs, debugging and root-cause diagnosis, on-demand advice, and core teaching material.
- Final review, acceptance, independent verification, Git mutations, and explanations to the owner.
- Recording the Git baseline and preserving every pre-existing user change.

Codex root may delegate only work the owner requested, whose contract is complete, and which belongs to the active milestone or phase. Every executor brief must contain an exact file allowlist. Overlapping write tasks and changes to a shared contract must be serialized. Read-only work and strictly disjoint writes may run in parallel, with no more than three active Sonnet 5 executors by default.

## Sonnet executor responsibilities

A Sonnet 5 executor performs one bounded implementation, transformation, exploration, test-writing, verification, or log-analysis task from a complete Codex brief. It must:

- Read this file and the complete brief before acting.
- Treat the brief's file allowlist as a hard write boundary.
- Follow established repository patterns and make the minimum necessary changes.
- Run only the verification commands named in the brief and accurately report commands and outcomes.
- Iterate on failures caused by its own edits while remaining inside the brief.
- Stop with `STATUS: needs_advice` when a decision or contract is missing.

An executor must not invent APIs, schemas, public names, dependencies, architecture, product behavior, or other contracts. It must not implement authentication or security-sensitive behavior unless the brief explicitly says the owner approved it and this file does not prohibit it. It must not orchestrate, spawn agents, perform Git mutations, install packages, mutate unspecified data, or do unrelated cleanup.

## Delegation boundaries

Do not delegate architecture, contract design, auth/security decisions, product or business decisions, billing, legal/privacy decisions, root-cause diagnosis, core teaching material, Git operations, or work spanning phases or milestones. These remain with Codex root unless the owner later changes this file explicitly.

Workers stop instead of inventing contracts. If requested work crosses an allowlist, protected domain, milestone, or established contract, return `STATUS: needs_advice` without making that part of the change.

## Review and verification

Worker output is evidence, not acceptance. After every executor run, Codex root must:

1. Compare `git status --short` with the recorded baseline.
2. Read every changed line and reject edits outside the allowlist.
3. Reject invented contracts, extra features, speculative abstractions, unrelated cleanup, weak tests, and false verification claims.
4. Request precise corrections in the same Claude session, stopping delegation after two failed correction rounds.
5. Independently rerun all relevant verification before acceptance.

Every Claude JSON result must be successful and its `modelUsage` must confirm `claude-sonnet-5`. Stop rather than accept a fallback model.

## Git and worktree safety

- Preserve every pre-existing user change; never attribute it to a worker or revert it.
- Never use `git reset`, `git checkout`, broad restoration, or destructive cleanup to correct worker output.
- Do not commit, amend, merge, rebase, push, or otherwise mutate Git unless the owner explicitly requests it. Git operations are performed by Codex root only.
- Inspect the worktree before delegation, after each executor, and before final acceptance.

## Product, legal, and security constraints

No product-specific legal, regulatory, privacy, safety, or data-handling requirements have been supplied. Their absence is not permission. Codex root must obtain and document applicable constraints before related implementation. Executors must stop for advice on any ambiguity involving credentials, permissions, personal data, external side effects, authentication, authorization, billing, legal terms, or security posture.
