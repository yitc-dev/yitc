---
name: local-first-consumer-contribution
class: discipline
sourced_from: 'owner directive 2026-06-30 (the don''t-wait → signal → bless-from-example → reconcile working mode) + external consult decisions/localfirst-contribution-mode-concept-audit-adhoc.yaml (FULL YELLOW, 3 findings absorbed) + the realized plan seed-and-grow-kernel-capability-and-yitc-ops-carri + the idea consumer-to-kernel-or-engineering-corpus-contribut. Prior-art (read-only): the framework "userland prototype → upstream → reconcile" cycle.'
applies_to: 'a CONSUMER that urgently needs a kernel/engineering-corpus SHAPE the kernel does not yet have — proceed local-first without blocking, signal the kernel, let the kernel bless from the real example, then reconcile. The temporal WHEN/HOW complement to the consumer→kernel three-tier triage idea (which answers WHERE a candidate goes). NOT a gate — a discipline; the only enforced anchor is the reconcile invariant (an OPEN cross item / tracked reconcile task).'
---

# Local-first consumer contribution — don't-wait → signal → bless-from-example → reconcile

> **Discipline pattern (the temporal contract of seed-and-grow).** The companion idea
> `consumer-to-kernel-or-engineering-corpus-contribut` answers WHERE a candidate goes (kernel /
> engineering-corpus / project — the three-tier triage). This pattern answers the complementary
> **WHEN/HOW**: how a consumer that urgently needs a shape the kernel lacks proceeds without
> blocking — and how the local↔kernel divergence is made to reconcile rather than rot.

## §Problem

A consumer hits a real, near-term need for a SHAPE the kernel does not have yet (a new ops-contract
section, a new lifecycle seam, a new concern class). Two bad extremes:

- **Block on the kernel** — the consumer's own work stalls waiting for a kernel design+ship cycle.
- **Diverge silently** — the consumer builds a local solution and never tells the kernel, so N
  projects each grow their own divergent home that never reconciles. This is exactly the v1 sprawl
  (95 gates / 60 hooks / 5 journals grew from un-reconciled local accretion) — CHARTER §What V2 is NOT.

Seed-and-grow needs a sanctioned middle: build locally NOW, but on a contract that forces the
local→kernel reconciliation to happen and stay visible.

## §Solution — the four-step working mode

1. **Build it locally NOW (don't wait).** The IMPLEMENTATION lives in the consumer's **normal project
   artifacts** (its own code / config — e.g. a vitest config + a render test). Mark it with a
   **`lesson`** (SPEC-0090) — the lesson is the **marked local RECORD**, NOT the implementation
   container: it carries pointers to the local impl, the **cross id**, and the **retire condition**
   ("retire when the kernel ships <X>"). Respect own safety under urgency: a land-layer stays
   **hermetic** (F-025), and "local" means the **project realm ONLY** (SPEC-0073) — never a
   consumer-authored shadow kernel surface.
2. **Signal the kernel** — `bin/yitc-v2 cross request` (the live channel, SPEC-0084/0085/0086),
   referencing the real local implementation as the worked example.
3. **Kernel blesses FROM the real example.** The working local impl is **EVIDENCE** (CHARTER §P1 F4 —
   a real incident / prior-art beats an imagined need), the preferred design basis. The kernel still
   applies its own lens (anti-complexity, the SPEC-0005 admission test, coherence) and **may bless a
   GENERALIZED shape** across projects — it ADOPTS the example, it does not rubber-stamp it.
4. **Reconcile (the enforced anchor).** The **cross item stays OPEN** — or spawns a tracked consumer
   **reconcile task** — **until the local provisional is retired OR explicitly deferred**. When the
   kernel ships the blessed form, the consumer migrates onto it and **RETIRES its local provisional**
   (and retires/updates the marking lesson) — **no two live homes** (CHARTER §P5). The open cross item
   (or reconcile task) is the visible reconcile-DEBT anchor; the `lesson-generalization-sweep` review
   lens is a **soft** backstop that works ONLY because the lesson record exists and stays visibly
   provisional — it is not, by itself, an enforcement gate.

## §Example — X-0140 (tests/verify layers, 2026-06-30)

`social-parser` added an admin-UI "Lifecycle" (Zhiznenny tsikl) view but its land gate (`yitc-verify.yaml`, a single
hermetic backend command) silently does not test the frontend. It is building a vitest+jsdom render
test **locally now** (a hermetic, project-realm test — step 1's safety honored), and signaled the
kernel via cross **X-0140** (step 2). The kernel SHIPPED a per-layer `verify.layers` carrier (each land
layer declare-or-waive, executable at `land` — run every layer / fail-on-any — RETIRING
the single `yitc-verify.yaml`) **from social-parser's real case as the basis** (step 3 — the seed-and-grow
tests/verify instance). On ship, social-parser reconciles its local vitest wiring onto the blessed
`yitc-ops.yaml verify.layers` form, X-0140 closing only then (step 4).

> **Instance not yet end-to-end:** step 1's **marked lesson** at social-parser (pointing at the local
> vitest wiring + citing X-0140 + the retire condition) is the consumer-side step still owed — it is
> authored in social-parser's own repo, not from the kernel session. Until it exists the local
> provisional is unmarked; the instance is faithful in shape but not yet fully evidenced.

## §Anti-pattern

- **Silent divergence** — building local with NO cross signal: the kernel never learns, N divergent
  homes accrue (the v1 sprawl this pattern exists to prevent).
- **Reconcile skipped** — the cross item closed as "paper proof" while the local workaround lives
  forever → permanent two-home drift. The OPEN-until-retired invariant (step 4) is what forbids this.
- **Shadow kernel** — a consumer authoring a kernel-realm surface under the banner of "local-first".
  "Local" is the project realm only (SPEC-0073).
- **Rubber-stamp** — the kernel adopting the local example verbatim without its own lens
  (anti-complexity / admission / coherence). The example is evidence, not the design.
- **Lesson-as-container** — putting the implementation INSIDE the lesson. A lesson is a marked record
  with pointers; the impl lives in the project's normal artifacts (SPEC-0090 §1/§5).

## §Cites

- `consumer-to-kernel-or-engineering-corpus-contribut` (the WHERE — three-tier triage; this is its WHEN/HOW complement)
- SPEC-0090 (the `lesson` node — the marked local-provisional record) · SPEC-0073 (placement realm — "local" = project)
- SPEC-0084 / SPEC-0085 / SPEC-0086 (the live cross signal channel) · CHARTER §P1 F4 (real example = evidence) · §P5 (no two homes)
- plan `seed-and-grow-kernel-capability-and-yitc-ops-carri` (the parent capability) · cross X-0140 (the live first instance)
- `lesson-generalization-sweep` review lens (the soft reconcile backstop)
