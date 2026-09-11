---
name: plan-finalization-runbook
class: discipline
sourced_from: owner-directive 2026-06-28 ( — "make the finalization runbook") + the migrate-trend-finder-onto-yitc-v2-v1-incumbent-gat finalization done ad hoc (re-grade→COMPLETE→close→plan realized orchestrated by hand) + SPEC-0034 (plan lifecycle per-stage mechanics + plan↔spec finalization chain) + SPEC-0070 (decomposition-fidelity audit) + SPEC-0036 (audit-loop ceiling) + patterns/realize-on-evidenced-soak-not-just-the-gate.md (the EVIDENCED-soak gate) + LIFECYCLE §Plan lifecycle + patterns/plan-lifecycle.md + the sibling navigational runbook patterns/inspection-triage-launch-runbook.md (format model)
applies_to: finalizing a plan that has reached the build's end — driving it postcheck → realized (or to a terminal partial/rejected/cancelled). Read BEFORE `plan stage realized`. This pattern is the SEQUENCING/navigation only — every rule it invokes homes elsewhere (it cites, it does not restate; SPEC-0005 rule 8 one-home). Provider-neutral by rule (CHARTER §P4b).
---

# Plan-finalization runbook — driving a plan postcheck → realized

> **What this IS:** a navigational ORDER — the named sequence of verbs to run to finalize a plan, each
> step pointing at the home that OWNS its rule. It restates **no** rule (CHARTER §P5 / SPEC-0005 rule 8
> — read the cited home for the actual gate / criterion / semantics) and adds **no** new mechanism,
> verb, gate, or store. The plan-axis sibling of `patterns/inspection-triage-launch-runbook.md`.

## §Problem

A plan's END — the `postcheck → realized` finalization — is a multi-step verb sequence whose steps and
gates are spread across SPEC-0034 / SPEC-0036 / the realize-on-evidenced-soak pattern / LIFECYCLE §Plan
lifecycle. There was **no named, repeatable runbook**, so each finalization (e.g. the
migrate-trend-finder plan) re-derived the order by hand. That ad-hoc re-derivation is the cost this
runbook removes (CHARTER §P1 F3): the finalization order becomes a named, grep-resolvable procedure.

## §The order (postcheck → realized)

Entry condition + where this applies: read SPEC-0034 §postcheck. Each line below = the verb to run +
the home that governs it; read the home for the rule — this is the ORDER, not the law.

1. **Re-orient** — `bin/yitc-v2 plan show <slug>` (read-only). Home: SPEC-0034.
2. **Confirm the build is settled** — `postcheck-plans-readiness` view + cited tasks. Home: SPEC-0034 §postcheck.
3. **Verify the soak is EVIDENCED** (not just `realize_ready`-flagged). Home: `patterns/realize-on-evidenced-soak-not-just-the-gate.md`.
4. **Aggregate finalization audit** (spec-bearing plans) — `bin/yitc-v2 audit post --plan <slug>`. Home: SPEC-0034 §realized; ceiling: SPEC-0036.
5. **Finalize** (in a `work/<slug>` worktree per AGENTS §Writes happen in a worktree) — `bin/yitc-v2 plan stage realized <slug> --into <IDs>`, then `bin/yitc-v2 land` from main. Home: SPEC-0034 §realized + GRAPH §Spec lifecycle.
   - **5b. Realized-by-record branch** — `plan stage realized <slug> --by-record --into <IDs> --soak-evidence <ref> --handoff <ref>`. Home: SPEC-0034 §Realized-by-record.
6. **Verify it landed** — plan `status: realized`; realized-spec corpus reads `active` (`graph query`). Home: GRAPH §Spec lifecycle.

## §Terminals (instead of realized)

`bin/yitc-v2 plan stage {partial|rejected|cancelled} <slug> …`. Required flags + semantics: LIFECYCLE §Plan lifecycle + SPEC-0034.

## §What this does NOT add

No new verb, gate, store, FSM, or rule — every step is an existing verb and every gate is enforced by
its existing home. This runbook is the ORDER, not the law (SPEC-0005 rule 8 — one home per rule).

## §Refs (the homes — read these for the actual rules)

- Plan lifecycle mechanics + plan↔spec finalization chain + aggregate `audit post --plan`: **SPEC-0034** (`bin/yitc-v2 graph query SPEC-0034`); procedure pointer `patterns/plan-lifecycle.md`.
- The EVIDENCED-soak gate: **`patterns/realize-on-evidenced-soak-not-just-the-gate.md`**.
- Audit-loop ceiling: **SPEC-0036**.
- Decomposition-fidelity audit (the upstream `decomposition → executing` gate): **SPEC-0070**.
- FSM skeleton + stage table: **LIFECYCLE.md §Plan lifecycle**.
- Format model: `patterns/inspection-triage-launch-runbook.md`.
