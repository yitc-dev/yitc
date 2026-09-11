---
name: audit-ceiling-consult-reopen-worked-example
class: discipline
sourced_from: SPEC-0124 §Audit-loop ceiling (the rule home) — re-homed from the spec body by per the protocol-weight compaction review §4a row P2-5 (owner-ruled 2026-07-17). Original example authored under.
applies_to: a session standing at an exhausted audit-loop ceiling that needs a re-audit pass — the consult -> `--owner-reset` re-open sequence, TASK pre or post
---

# Pattern: the consult → `--owner-reset` re-open sequence (worked example)

> **NON-NORMATIVE illustration. The RULE lives in SPEC-0124 §Audit-loop ceiling**
> (`bin/yitc-v2 graph query SPEC-0124`) — specifically §Owner-authorized ceiling continuation
> (`--owner-reset`), its RE-OPEN bullet and its THE ESCAPE bullet. On ANY conflict, SPEC-0124 WINS.
> This file teaches the sequence; it establishes no rule and adds no gate.
>
> **Why it lives here:** SPEC-0124 is delivered at BOTH the Audit-pre and Audit-post stage-entries, so
> every substantive task paid this example twice before ever needing it. It has genuine teaching value
> but no behavioral moment-of-use at delivery time (Bucket 3 — illustration), so it is read ON DEMAND,
> at the moment a ceiling is actually exhausted.

## When to read this

You are at an audit-loop ceiling, the findings are ACTUALLY fixed, and you need to know how a pass is
legitimately re-earned — or why yours is refused. If you have not hit a ceiling, you do not need this.

## The sequence (POST stage)

A worked example of the SPEC-0124 re-open invariant — an in-progress task at Audit-post whose absorb
loop exhausts the budget, is re-resolved, and re-earns the pass via a FRESH converged consult:

1. `audit post` → RED (pass-1). Absorb the finding mode-a (re-implement), re-audit.
2. `audit post` → RED (pass-2). `passes == AUDIT_PASS_CEILING` — the ceiling is now REACHED.
3. The findings are ACTUALLY fixed → `audit consult --task --stage post` → converges to a SINGLE
   GREEN survivor (`basis_fingerprint` = the current commit SHA). → `audit post --owner-reset`
   VERIFIES that fresh single-survivor basis → grants pass-3, `owner_reset_basis: consult:<file>`,
   `consult_governed: true` (verdict carried VERBATIM — no routine re-RED).
4. Pass-3 RED's on a NEW residual (e.g. a coherence/authoring finding the consult had not covered).
   The budget is now EXHAUSTED — the single `--owner-reset` was spent on pass-3, so a plain
   `audit post --owner-reset` here would REFUSE (pass-4 blocked).
5. Re-resolve that residual, then RE-RUN the FULL consult: `audit consult --task --stage post` →
   converges single-survivor GREEN, its recorded `passes >= prior_passes` (the POST freshness
   axis — a consult re-RUN after the last recorded pass, NOT necessarily a commit change).
6. That fresh converged consult RE-OPENS one more `--owner-reset`: `audit post --owner-reset`
   verifies the re-run consult's `basis_fingerprint` == current commit SHA → grants pass-4,
   consult-governed GREEN → proceed to Closure. (Symmetric on the PRE stage, whose re-open axis is
   instead a real plan change: `plan_fingerprint` != the prior recorded fingerprint.)

## When it does NOT re-open — THE ESCAPE

At step 5/6 the `--owner-reset` REFUSES → escalate-to-owner (never a silent pass-4) when the budget
stays hard-exhausted. The four conditions are **normative and exhaustive in SPEC-0124 §Owner-authorized
ceiling continuation → THE ESCAPE** — read them there, not here: (a) multi-survivor re-run consult,
(b) ABORT, (c) stale `basis_fingerprint`, (d) no fresh consult at all. A hard-exhausted budget with no
fresh single-survivor convergence is a genuine non-convergence — the owner is the backstop
(CHARTER §P6), exactly as the «pass-4 not» clause intends.

## The trap in condition (c): "stale basis" after YOU absorbed is not the escape

> Routed **traveling to `patterns/`** per SPEC-0090 §2: SPEC-0124's ceiling and its consult sequence
> are delivered at BOTH audit stage-entries in every repo, so this is YITC methodology the engine and
> every consumer operate by — not kernel-codebase trivia. It extends this existing worked example
> rather than opening a new file, because it is a clarification of steps 5-6 above.

Condition (c) above — a **stale `basis_fingerprint`** — is listed under WHEN IT DOES NOT RE-OPEN. Read
in isolation at the moment you are standing at an exhausted ceiling, it looks like a dead end: your
basis IS stale, so the escape says escalate.

It is a dead end only in the case the list means: stale **with no fresh consult**. There is a much
more common way to arrive at a stale basis, and it has an exit that needs no owner at all.

**Absorbing a finding by a NEW commit stales the basis BY CONSTRUCTION.** The consult's
`basis_fingerprint` is the commit SHA it ran against. Fixing the finding it raised necessarily
produces a *different* SHA — the fix postdates the consult. So a correctly-executed absorption
**always** leaves the prior consult stale. Staleness here is evidence that you did the work, not
evidence that you are out of road.

**The exit is step 5, and it comes before any owner ask:** re-run the consult against the **absorbed
tree**. If it re-converges to the same single survivor, that fresh convergence re-opens the
`--owner-reset` (step 6) and the pass is granted — consult-governed, no fresh owner authorization
required.

 escalated to the owner at this point instead, spending a round-trip on a decision the verb
resolves by itself. The distinction, stated as a question to ask at the ceiling:

    my basis is stale because I ABSORBED and re-committed
        -> re-run the consult FIRST; convergence re-opens the pass (steps 5-6)
    my basis is stale and a re-run consult does NOT re-converge
    (multi-survivor / ABORT / no fresh consult at all)
        -> genuine non-convergence; escalate per THE ESCAPE

Only the second is escape-condition (c). Reaching for the owner before the re-run reads as a
non-convergence that was never actually tested.

## References

- **SPEC-0124** — the rule home (§Audit-loop ceiling; §Owner-authorized ceiling continuation).
- **SPEC-0036** — the external-auditor invocation/verdict contract.
- **** — the incident behind §The trap in condition (c): an owner escalation spent before the
  re-run consult that would have re-opened the pass. Routed here by.
- **LIFECYCLE §Stage 4 / §Stage 8** — the mode-a / mode-b absorption fork that decides whether a
  finding costs a pass at all (most ceilings are reached by pushing a PASSABLE finding through mode-a
  — see SPEC-0124 §Ledger-skip axes → passable-absorption).
