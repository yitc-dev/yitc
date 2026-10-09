---
name: audit-ceiling-consult-reopen-worked-example
class: discipline
sourced_from: SPEC-0204 (the rule home for what happens once the audit-loop ceiling is reached) + SPEC-0124 §Audit-loop ceiling (the ceiling itself). Rewritten by (fu_e2241c8fa6c4) for the SPEC-0204 decision route. The path keeps its historical name because SPEC-0124 part2 links it; the earlier consult -> `--owner-reset` example (re-homed, extended by) describes a route SPEC-0204 rule 6 retired.
applies_to: a session standing at an exhausted audit-loop ceiling, TASK audit-pre or audit-post — the Worker that halts there, and the Controller that records the decisions
---

# Pattern: at the audit-loop ceiling — the SPEC-0204 decision route (worked example)

> **NON-NORMATIVE illustration. The RULE lives in SPEC-0204** (`bin/yitc-v2 graph query SPEC-0204`);
> the ceiling arithmetic itself stays in SPEC-0124 §Audit-loop ceiling. On ANY conflict, SPEC-0204
> WINS. This file teaches the sequence; it establishes no rule and adds no gate.
>
> **Why it lives here:** a worked example inside SPEC-0204 would be paid by everyone who fetches the
> rule, before anyone needs the walk-through. It is read ON DEMAND, when a ceiling is actually reached
> (no stage entry renders SPEC-0204 or SPEC-0124 since; SPEC-0036 §Audit-loop ceiling names them).

## When to read this

Your `audit pre` or `audit post` has used its absorption passes and the last pass is still RED. If you
have not hit a ceiling, you do not need this.

## The sequence (a real audit-pre instance:, 2026-09-23)

1. **Pass 1 → RED, pass 2 → RED.** The card absorbed the first finding (mode-a: plan edited,
   re-audited), and the second pass raised a new high finding. With two passes spent, the ceiling is
   REACHED. The verb does not loop and does not consult.
2. **The residuals ARE the last RED's findings.** There is no separate survey. Each residual carries an
   ENGINE-computed fingerprint (e.g. `fp1:bf015a3000b1f8dd`), printed by the verb and carried on the
   ceiling row. Copy it, never recompute it by hand.
3. **The Worker HALTS.** `audit pre|post` itself emits the `bg_dispatch_halted` row naming the residual
   fingerprints, so the Worker owes no second row. The Worker then runs
   `bin/yitc-v2 task pause T-XXXX --reason audit-ceiling` inside its worktree. That keeps the worktree
   INTACT and records the resume contract. A Worker never decides its own residuals. (Before the first
   commit, `blocked-on-land` refuses by design; `task pause` is the verb for that window.)
4. **The Controller records ONE typed decision per residual.** One `audit decide` call per
   fingerprint, citing the owner directive that authorizes it:
   - `fix` — a change follows; `--evidence <revision>` names the ONE revision the fix produces (the new
     plan fingerprint at audit-pre, a descendant commit at audit-post);
   - `accept` — the residual stands; the reason quotes the authorizing words;
   - `defer` — the work rides a named receiving card (`--receiving T-YYYY`).

   In the one residual was a spec-coherence finding (a SPEC-0124 pointer that would go stale).
   The Worker amended the plan to include that pointer edit, re-finalized it, and stopped with
   `--reason controller-wait` so the Controller could record `--disposition fix` against the new plan
   fingerprint.
5. **The Worker resumes and runs exactly ONE bounded pass.** `task resume`, then
   `audit pre|post --task T-XXXX --on-decisions`. The verb admits the pass only when EVERY residual has a
   decision and the audited subject is the revision those decisions name. Otherwise it refuses and
   names the undecided residual or the mismatched revision. `--on-decisions` cannot be combined with
   `--preview`, so run `--preview` alone first.
6. **Outcome.** GREEN, or YELLOW absorbed → proceed (Execution after audit-pre, Closure after
   audit-post). A new small finding on that pass is absorbed like any YELLOW. RED again (a new high
   finding, or a `fix` still open) is TERMINAL for the card's audit status: the only exits are the
   owner's existing terminal dispositions. There is no second `--on-decisions` pass.

 took this route: the `--on-decisions` pass came back GREEN on the amended plan, and the card
went on to Execution.

## The retired route — history only

Before SPEC-0204, a ceiling was re-opened by an `audit consult` episode whose converged survivor let
`audit pre|post --owner-reset` grant one more pass, re-openable by a fresh consult (and `--reopen`).
SPEC-0204 rule 6 RETIRED all of it: consult episodes for ceiling adjudication, `--reopen`,
`--owner-reset`, and the dispatched-worker auto-consult. Each retired flag now REFUSES with a pointer to
`audit decide` / `--on-decisions`. If you find older records or lessons that describe the consult →
`--owner-reset` sequence, read them as history. `audit consult --on-demand` (the BELOW-ceiling
technical-fork pick) is a different thing and is unchanged.

## References

- **SPEC-0204** — the rule home: residuals (rule 1), `ceiling_decision` (rule 2), the one bounded
  pass (rule 3), custody (rule 4), retirements (rule 6).
- **SPEC-0124** — the ceiling itself (pass arithmetic, ledger-skips).
- **SPEC-0103 §3 / §5** — the Worker's halt and the work-carrying pause shape.
- **LIFECYCLE §Stage 4 / §Stage 8** — the mode-a / mode-b absorption fork. Most ceilings are reached
  by pushing a PASSABLE finding through mode-a; recording it with mode-b (`--absorb`) spends no pass.
