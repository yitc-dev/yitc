---
name: post-ship-soak-observation
class: discipline
sourced_from: plan task-burn-in-soak-period-post-closure-observation- (realized 2026-06-03) — distilled as trial run #5 of plan systematic-reusable-craft-lesson-capture-at-closur (Vehicle 3, SPEC-0089)
applies_to: deciding whether/how to OBSERVE shipped work in real operation after closure (latent-defect classes invisible at ship time). Sibling of patterns/trial-methods.md — trial = PRE-build design convergence; soak = POST-build operation. Read when a change has a failure mode only real running surfaces.
---

# Pattern: post-ship soak observation — observe the SHIP, don't gate it

## Problem

Some defect classes are invisible at ship time and only surface in real operation over a window. Trial
(pre-build) discovers design edge cases; point-in-time verification ratifies one run. Neither watches
the SHIPPED code hold up over time. But adding a soak must not become a daemon/timer/new-status apparatus.

## Solution

1. **Soak the SHIP, not the design.** Trial (pre-build, `patterns/trial-methods.md`) and soak
   (post-build) are a non-conflatable pair — don't merge them.
2. **Author the per-task success `criterion + signal` at the moment of best understanding** (Closure),
   not guessed later by an inspector.
3. **Reuse the existing window** — `postcheck` (plan-level) + the adoption sub-lens; add a light
   per-task soak ONLY for the work-first gap (a task with no plan → no postcheck → no soak).
4. **Observe, don't gate.** A soaking task is `done` / "settling" — advisory only. NO new status, NO
   daemon/timer, NO stored soak-state, NO queue view (the negative-acceptance contract).
5. **Graduate on N POSITIVE confirmations, never on N windows of silence.**

## Anti-pattern

- **null ≠ clean (decisive):** "the signal was never observed" = still BLIND, NOT settled. Silence is
  not evidence; graduate only on positive confirmations.
- **A self-defeating trigger:** a latent-defect class is invisible WITHOUT the instrument, so "wait for
  an incident before adding the soak" can never fire — justify the soak on prior-art / external-analog
  instead (this is the P1-F4 exception the soak class legitimately needs).
- **Building soak infra** (a status, a timer, a stored state, a queue lens) — observe via the existing
  journal + postcheck window; do not stand up apparatus.

## Cites

- `patterns/trial-methods.md` — the PRE-build sibling (trial = design convergence; this = post-ship operation).
- `patterns/verification-protocol.md` — point-in-time post-work ratification (distinct from a time-windowed soak).
- plan `task-burn-in-soak-period-post-closure-observation-` (0354/0355) — the source.
- `SPEC-0089` — the reflection discipline that produced this entry (trial run #5).
