---
name: session-tooling-discipline
class: discipline
sourced_from: migrated from the global memory `feedback_yitc_v2_session_discipline` ( AC3 sweep) / (the originating incidents) + AGENTS §Writes-happen-in-a-worktree (worktree-flow half, already homed)
applies_to: every V2 Build/Review session — the operational tool-call discipline that keeps the worktree+verb flow from corrupting state. Read alongside AGENTS §Writes-happen-in-a-worktree.
---

# Session tooling discipline — how to drive the tools without corrupting state

## Problem

The V2 flow (worktree + verbs + land) is safe ONLY if the agent drives the tools with a few
operational habits. Two failure shapes recur: (1) the primary AI harness executes multiple tool calls
in one message **in parallel**, and a failure in one **cancels its siblings** (`Cancelled: parallel
tool call errored`) — a harness-level effect, unreachable from verb design (noted in
[[verb-design]] :: "parallel-tool-call cascade … harness-level"; root incident Slip 3);
(2) commands that assume a checkout/cwd that a prior `land` already deleted, or hand-chosen ids/SHAs
that drift from the verbs' truth. AGENTS §Writes-happen-in-a-worktree homes the worktree/claim/land
shape; this pattern homes the **tool-call habits** that the worktree shape relies on but does not state.

## Solution — the habits

- **One mutating tool call per message.** Never batch dependent or state-mutating calls in a single
  message — a sibling failure cancels the rest, leaving partial state. Parallelise ONLY independent
  read-only calls. One `Edit` per file at a time.
- **Never chain a command after `land`.** `land` removes the worktree dir on success, so any command
  in the same message lands in a deleted cwd (`getcwd` error). Run `land` alone, then follow its
  printed `cd <main>` cue as a separate step.
- **Bind every command to its checkout.** Use absolute paths or `git -C <path>`; verify a write in the
  SAME checkout you wrote it (a relative grep from another checkout gives a false 0 — Slip 5).
- **IDs come from verbs, never hand-picked.** `task file` / `spec new` allocate the id; do not invent
  `T-`/`SPEC-` numbers (collision + drift).
- **SHAs come from verb output.** Take the commit SHA from `task commit`'s output; `audit post` /
  `task close` `--commit` consume the real recorded SHA, never a hand-typed value ( chain-of-custody).
- **Read a verb's output WHOLE — never filter it at the pipe.** A `tail`/`grep`/`head` applied at
  invocation discards the verdict / guidance / next-step you did not know was there, and a mutating
  verb cannot be re-run to re-read it. Rule + the one contracted-token exception:
  [[consume-verb-output-whole]].
- **Audit `passes` accumulate.** Each `audit pre|post` invocation increments the per-task-per-stage
  pass counter (ceiling = 2). Do not re-run an audit to "re-check" — absorb residual findings by
  RECORDING them (LIFECYCLE §Stage 4 mode-b), not by burning a pass.
- **Headless/cron invocations prepend `session start`.** A non-interactive caller (cron line, a
  provisioning/onboarding script, any automation) that runs a GOVERNED kernel `yitc-v2` verb — the
  headless-automation ones are `nightly`, `memory seed`, `-C init` — has NO interactive `session start`
  behind it, so it MUST self-back its identity: chain
  `<engine>/bin/yitc-v2 [-C <path>] session start >/dev/null && <engine>/bin/yitc-v2 [-C <path>] <verb> …`
  (use an ABSOLUTE engine path in a script, not a cwd-relative `bin/yitc-v2`; optionally carry a
  v2-minted `YITC_SESSION_REF`). Without a live session RECORD the verb fails closed (SPEC-0137
  Rule 1/5, `_require_seed_read` / `_resolve_session_ref`) — a bare carried ref does NOT win for keying
  (the X-0158 fix), so a missed `session start` degrades to a silent no-op behind any `|| echo WARN`
  fallback. Read verbs (`graph query`, `task list`, …) are exempt — they are not gated. The three
  inventory-gated verbs (`worktree new`, `task file`, `land`) additionally require a one-time
  `--help` verb-inventory scan this session (X-0158), but those are interactive worker-stage
  verbs, not headless-automation entry points — `session start` alone backs the automation verbs above
  (proven: `session start && memory seed` resolves; the bare `memory seed` fails closed).

## Example

In and each mutating step (`worktree new`, `task plan --finalize`, every `Edit`,
`task commit`, `land`) was issued as its own message; `land` was run alone and followed by a separate
`cd` to the main checkout. hit the audit `passes` ceiling exactly because re-auditing burns a
pass — the residuals were then absorbed by recording, per the last habit.

## Anti-pattern

Batching `worktree new` + an `Edit` + `task commit` in one message "to save round-trips" — the first
failure cancels the rest and the claim/commit state is left half-written. Equally: chaining `cd` or a
grep after `land` in the same breath (dead cwd), or typing a commit SHA from memory into `audit post`.

## Cites

- / (originating incidents); AGENTS §Writes-happen-in-a-worktree (worktree/claim/land flow)
- [[verb-design]] (the cascade is harness-level, unreachable from verbs); (land deletes the cwd)
- LIFECYCLE §Stage 4 (audit-loop ceiling = 2; absorb residuals by recording — mode-b)
- AC3 ([[global-memory-v2-migration-sweep]]) — this pattern is the migration of `feedback_yitc_v2_session_discipline`
- SPEC-0137 (v2-owned session identity — fail-closed resolution) + the X-0158 unbacked-carry class; the
  headless session-start-first habit was swept in by (yitc-v2-nightly cron + create-project.sh
  already backed; provision-user.sh `memory seed` was the found break, fixed by prepending `session start`)
