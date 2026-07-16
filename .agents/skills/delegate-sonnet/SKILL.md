---
name: delegate-sonnet
description: Delegate bounded work from Codex root to Claude Code pinned to claude-sonnet-5. Use for read-only repository exploration; exact seed or data transformations; fixtures from an approved case list; scaffolding that follows an established pattern; mechanical migrations, repetitive implementation, or mechanical refactors under a complete contract; specified test writing; and verification or log analysis. Do not use for architecture, public API or schema design, authentication or security decisions, root-cause diagnosis, core teaching material, Git operations, or work spanning phases or milestones.
---

# Delegate to Sonnet 5

Keep Codex root as the only orchestrator. Launch Sonnet work through the local Claude Code CLI; never label a native Codex subagent as Sonnet. Follow `AGENTS.md` as the durable source of repository rules.

## A. Qualify

Before delegating:

1. Confirm the owner requested the work.
2. Confirm the established contract fully specifies the bounded result.
3. Confirm the work belongs to the active milestone or phase.
4. Keep architecture, public contracts, auth/security decisions, root-cause diagnosis, core teaching, Git operations, and cross-phase work with Codex root.

If any condition fails, do not delegate.

## B. Baseline

Run `git status --short`. Record every pre-existing change before starting an executor. Never attribute a baseline change to a worker and never revert it as worker output.

## C. Fan out

Split qualified work into independent bounded briefs. Use at most three active Sonnet 5 executors by default. Parallelize read-only tasks and strictly disjoint writes. Serialize overlapping writes and shared-contract changes.

## D. Write the brief

Include every section below in every executor brief:

```text
GOAL
ACTIVE MILESTONE OR PHASE
FILE ALLOWLIST
ESTABLISHED CONTRACT
PATTERN TO COPY
REQUIRED CHANGES
FORBIDDEN CHANGES
VERIFICATION COMMANDS
DEFINITION OF DONE
STOP CONDITIONS
REPORT FORMAT
```

Make `FILE ALLOWLIST` exact. State that it is a hard write boundary. Put all public names, schemas, APIs, dependencies, approved cases, and owner decisions needed for the task in `ESTABLISHED CONTRACT`. Give file-and-line pointers in `PATTERN TO COPY`. Limit verification to commands the executor may run. In `STOP CONDITIONS`, require `STATUS: needs_advice` for missing decisions, ambiguity, boundary conflicts, or contract gaps. In `REPORT FORMAT`, require the exact headings from `CLAUDE.md`.

## E. Start a write executor

Run:

```sh
claude --print \
  --model claude-sonnet-5 \
  --agent project-worker \
  --output-format json \
  "$BRIEF"
```

## F. Start an explorer

Run:

```sh
claude --print \
  --model claude-sonnet-5 \
  --agent project-explorer \
  --output-format json \
  "$BRIEF"
```

Preserve every returned `session_id`. Require a successful JSON result and require `modelUsage` to contain `claude-sonnet-5`; stop rather than silently accepting another model. If repository sandboxing blocks Claude credential or session files, request narrowly scoped approval for the bounded `claude --print ...` command. Never disable sandboxing globally.

## G. Run the advisor loop

When the executor reports `STATUS: needs_advice`, inspect the repository and decide the issue as Codex root. Resume the same session:

```sh
claude --print \
  --resume "$SESSION_ID" \
  --output-format json \
  "ADVISOR DECISION: <decision and rationale>. Continue the original brief within the existing allowlist."
```

Send the decision and rationale, not a replacement implementation. Recheck successful JSON and `modelUsage.claude-sonnet-5` after every resume.

## H. Run the review loop

After each executor completes:

1. Run `git status --short` and compare it with the baseline.
2. Read every changed line.
3. Reject edits outside the allowlist.
4. Reject invented contracts, extra features, speculative abstractions, unrelated cleanup, weak tests, and false verification claims.
5. Resume the same session with precise review findings when correction is required.
6. Stop delegating after two failed correction rounds.

Never use `git reset`, `git checkout`, or broad restoration to clean worker mistakes. Correct only known worker lines with precise edits or ask the owner when provenance is unclear.

## I. Verify

Independently rerun every relevant verification command as Codex root. Treat worker output as evidence, not acceptance. Confirm the final worktree contains no out-of-scope changes.

## J. Explain

Summarize accepted delegated changes, independent verification, and anything the owner needs to understand. Distinguish baseline user changes from accepted executor output.
