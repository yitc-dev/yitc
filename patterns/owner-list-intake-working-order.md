---
name: owner-list-intake-working-order
class: discipline
sourced_from: kupiclub plan owner-list-intake-working-order-trial-in-kupiclub- (status realized, owner-judged converged 2026-06-22) + lesson owner-list-intake-working-order (read-only provenance)
applies_to: any project — when the owner states a LIST of to-dos / behaviour changes to process in one go (the "owner dumps several things to do" intake)
---

# Owner-list intake working-order

## Problem

When the owner proposes a LIST of to-dos (several behaviour changes at once), the governing pieces
all already exist — but **scattered**: decompose (SPEC-0046), classify (SPEC-0008), dispatch
(CHARTER §6 + `patterns/background-session-operation.md`), the owner checkpoint
(AGENTS §Recommendation Default), verify-on-land (`patterns/background-session-operation.md`). The
**ORDER** in which to apply them is not written down anywhere, so each intake re-derives it under load
and drifts: a stale premise gets acted on, a UX/scenario change gets under-swept (treated as a
one-liner), or a Build worker gets mis-launched as an in-process subagent instead of via
`bin/yitc-v2 dispatch`. This pattern homes the converged ORDER — a thin wrapper that sequences the
existing disciplines; it does NOT restate any of them.

> **Boundary (single-home, P5).** `patterns/background-session-operation.md` stays the EXECUTION home
> (how to launch / select / monitor / recover background Build workers — step 5's machinery). THIS
> pattern is ONLY the owner-list **intake working-order** — the wrapper that decides what becomes a
> task and in what sequence, then HANDS step 5 to that execution home. When the two could overlap, the
> execution mechanics live there; the intake sequence lives here.

## The working-order (steps 0→6)

Each step **cues** its discipline and **points** to the home that owns the rule — read the home for
the actual rule-text (this is a sequence, not a restatement).

0. **Journal is the source — do NOT create a list file.** Owner input materializes in `events.jsonl`
   as `owner_directive` (verbatim). There is no separate intake-list artifact (Principle 5 +
   anti-over-process). The list disperses into governed homes: `tasks/` is the single "what to do";
   `plans/` for a cluster; `ideas/` for a later seed; the cross-log for kernel / another project.
1. **Verify each premise by fact.** Re-read the current state per item before acting — never act on the
   owner's (or your own) stale description. (Prior-art: a "graph build broken" premise that was green.)
   **For a cross-log item, its `[picked]`/`[done]` status is itself a stop-and-check: a picked/resolved
   request is NOT fresh work — the request TEXT is the frozen original ask, not current state, so
   `grep resolves_cross <X-ID> tasks/*.yaml` (and find any resolving plan) BEFORE proposing a new
   carrier. Skip this and you re-file a duplicate of already-shipped work** (X-0140, 2026-07-02: a done
   plan re-proposed as a fresh plan authored from the request's stale original text — fingerprint
   `duplicate-plan-for-already-shipped-cross-request-x0140`).
   **A cross-INBOX item you are about to take in is governed — read the rule, don't re-derive it here:**
   the receiver-side premise review owed before any `cross pick` / `resolves_cross` filing (what to verify,
   and the four outcomes incl. the requester-visible reframe duty) is homed in **SPEC-0086 rule 7**
   (`bin/yitc-v2 graph query SPEC-0086`) — this step only CUES it (pointer, not a restatement — P5).
2. **Classify each item inline — the one-question test.** binding rule → a `spec` · UX / user-path →
   a `scenario` step + task · chore → a hygiene task · kernel / another project → the cross-log ·
   genuinely-later → `ideas/`. For a scenario item, sweep the FULL surface (every scenario + narration
   coherence), not one line.
3. **Decompose + batch + order.** ONE provable claim per task (SPEC-0046 — the cut authority); batch by
   shared specs/files; order by `requires:`; mark independent vs chained. **Claim-shape decides the
   drain UNIT (the primary economy lever):** same-claim / homogeneous to-dos → ONE task (one
   lifecycle, one audit); different-claim to-dos → separate tasks (a hygiene text-trim and an audited
   feature CANNOT be one task — different claims AND classes).
4. **ONE owner checkpoint.** Present the classified + batched list, the real forks, and what is
   deferred — **recommendation-first, no menu** (AGENTS §Recommendation Default). Owner: go / redirect.
5. **Execute via `bin/yitc-v2 dispatch`** — background Build workers, **NEVER an in-process subagent**
   (CHARTER §6). The controller files the task first, THEN dispatches (the dispatch verb needs the task
   id to exist). Pick the mode by claim-shape + size (full procedure: the EXECUTION home
   `patterns/background-session-dispatch.md §Dispatch launcher`): substantial / risky independents →
   parallel workers; a batch of SMALL independent tasks that can't merge → front-load into ONE warm
   worker (bootstrap paid once); a `requires:`-chain or land-conflict pair → one warm worker, chained.
   Dispatch's value even for a tiny task is **controller-context offload** — the reads / edits / audit
   noise land in the disposable worker, not the main session.
6. **Verify each landed result by fact + close loops.** Confirm each `land` by fact (not by the
   worker's claim); close any cross-log loops (via `cross` outbox).

**The staging buffer is the `followup` verb (SPEC-0095)** — a small follow-up that arises mid-flow is
captured with `bin/yitc-v2 followup add` (a journaled, no-worktree capture), drained as a batch via
steps 2→3. (This SUPERSEDES the old markdown `ideas/followups-inbox.md` stand-in — retired.)

**Holds throughout:** anti-complexity per item (file an adjacent find, do not grow the current scope);
the deviation-capture reflex; NO auto-processed accumulation / auto-re-emit (a passive cue-drained
staging surface is fine; manufacturing owner-questions when the owner is disengaged is not); `ideas/`
is pulled only on an owner cue.

## Why it travels

The order is general YITC methodology (it sequences kernel disciplines, no project specifics), so it
is a `patterns/` traveling pattern, not a `lessons/` local note. Project-local craft about running it
in one codebase (which files collide, which surface is the recurring target) stays in that repo's
`lessons/`. Converged over two real kupiclub to-do batches (owner-judged 2026-06-22) before homing.
