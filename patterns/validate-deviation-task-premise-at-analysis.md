---
name: validate-deviation-task-premise-at-analysis
class: discipline
sourced_from: 'Vehicle-2 closure reflection of (lesson-capture trial, 2026-06-21): a task filed FROM a deviation ("regenerate release-view at land") was found at Stage-1 Analysis to contradict an active spec (SPEC-0074 §6 explicit-build-only) + re-invent existing tooling — caught before any code was written.'
applies_to: 'Stage-1 Analysis of ANY task filed from a deviation_captured / bug-report / friction (a task whose premise is "X should happen / X is missing"). Read BEFORE designing the fix.'
---

# Pattern: validate a deviation-framed task's PREMISE at Analysis

## Problem

A `deviation_captured` is logged at the friction MOMENT — a reflex, with no design context (by design:
capture is not judgement). When that deviation later becomes a task, its title carries an implied
PREMISE about the fix: "X is missing → add X", "X should happen at Y". But the friction moment did not
know WHY the system behaves as it does. The premise can be wrong in two expensive ways:

1. **It contradicts a deliberate design** — the "missing" behaviour was excluded ON PURPOSE by an active
   spec. Building it silently violates the spec (CHARTER §P7 dissonance).
2. **It re-invents existing tooling** — the capability already exists (a detector, a verb, a periodic
   check), so the "new mechanism" duplicates it (CHARTER §P1 F1 / failure-class #5).

A task's premise feels settled because it came from a real friction — so the Analysis prior-art sweep
gets skipped or done shallowly ("the friction is real, so the fix must be real"). That is the trap.

## Solution

At Stage-1 Analysis of a deviation-framed task, before designing the fix, ASK:

1. **Is the behaviour the task wants to change DELIBERATE?** Read the spec that governs the surface (not
   just "is there an analog?" — *why* is it this way?). A spec rule like "explicit-build-only, NOT in
   land" is a design decision, not an oversight. If the premise contradicts it → STOP, it is a P7
   dissonance: capture it, surface to the owner, do not build against the spec.
2. **Does the capability already exist?** Sweep code/verb/pattern/spec for a detector + a fix-path. A
   "missing mechanism" is often a deliberate detect-and-explicit-fix design (a drift detector + a
   regen verb), not a gap to fill with automation.
3. **Reshape, don't force.** If the premise is wrong, reshape the task to the COHERENT residual (e.g.
   "run the existing fix verb + commit") or `wont-do` it — never build the contradicting mechanism to
   honour the original title.

The friction is real; the *framing of its fix* is a hypothesis Analysis must test.

### Validate at FILING too, not only at Analysis (2026-06-21 — 2nd-occurrence refinement)

Two deviation-framed tasks filed back-to-back ( "regen at land" "add a grace signal")
BOTH carried a re-invention premise — each caught only at its own Stage-1 Analysis, after the card was
already filed + claimed + a worktree opened. Cheaper: run the same premise check **when turning a
deviation into a task** (filing / triage), so a re-invention card is reshaped or never filed. The
deviation-capture moment legitimately records only the friction (SPEC-0056 §1 — capture gathers, does
not judge); the JUDGEMENT belongs at the first point someone proposes a fix — that is filing, one step
earlier than Analysis. Analysis stays the backstop, not the sole gate.

### Check 3 — was this FINGERPRINT already routed and CLOSED? (2026-08-13)

> Routed **traveling to `patterns/`** per SPEC-0090 §2: deviation-framed premise validation is general
> YITC methodology every repo's Analysis runs, and the cross log + deviation fingerprints are kernel
> machinery shipped everywhere. It extends this entry rather than standing alone because it is a third
> instance of this pattern's own claim — the premise is a hypothesis — not a distinct discipline.

Checks 1-2 ask whether the premise contradicts a design or duplicates a capability. A third way a
premise is already dead: **the same deviation was routed and CLOSED under a different id.**

 asked for a guard. Its triggering deviation, X-0845, turned out to be a **re-capture of the
identical row already resolved as X-0044** — same fingerprint, same incident, the same morning. The
decisive move was not a code search; it was a **fingerprint search across the cross log**. A
re-capture of an unrouted row is easy to produce (the row looks unhandled because the capture is new)
and it duplicates an item that is already closed.

Three concrete moves, in the order they pay off:

1. **Grep the cross log by `origin_fp`, not only by prose.** Whenever a card says "routed late" or
   "never reached the kernel", the fingerprint is the join key. Prose describing the same incident
   twice rarely matches itself; the fingerprint always does.
2. **When the class has a shipped DETECTOR, run it over real history** instead of reasoning about
   reachability — and **run it in the journal instance that actually SEES the class**. A `-C` consumer
   dispatch never appears in the kernel journal: the same detector read **0 launches** in one instance
   and **201** in the other. An answer of "zero" from the wrong instance is indistinguishable from a
   real absence.
3. **Check whether a prior LANDED change already DECLINED the guard on purpose.** AC3 had
   declined this exact guard deliberately. Building it would have contradicted a landed decision on no
   new evidence — check 1's spec-deliberate trap, arriving through a closed task rather than a spec.

The shape shared with checks 1-2: the friction is real, and the card's account of *what remains to be
done about it* is the hypothesis. Here the hypothesis is "this is unhandled" — and the cheapest test
is a fingerprint lookup, not a design session.

## Anti-pattern

- **Implementing a deviation-task's title verbatim** because "the friction was real" — without checking
  whether the targeted behaviour is spec-deliberate.
- **Adding a mechanism the design deliberately excluded** (the contradiction surfaces only later, or
  ships as silent drift).
- **Filing the fix-framing INTO the deviation** at capture time as if settled — capture the friction
  (what hurt), not a pre-judged fix (SPEC-0056 §1: triage gathers, Analysis judges).

## Cites

- `SPEC-0032` — Stage-1 Analysis procedure (the prior-art sweep this sharpens — *why*, not just *whether*).
- `SPEC-0056` — deviation triage (capture gathers; how-to-fix is decided downstream, not at capture).
- `CHARTER.md#principle-7` — dissonance is a question; a premise contradicting a spec is a STOP.
- `CHARTER.md#principle-1` — anti-complexity F1 (existing analog) + failure-class #5 (re-invention).
- `SPEC-0089` — the reflection discipline; this is its Vehicle-2 trial output ( closure).
- `` — check 3's incident (X-0845 a re-capture of the already-closed X-0044; AC3 had
  deliberately declined the same guard). Routed here by.
