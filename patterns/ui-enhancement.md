---
name: ui-enhancement
class: discipline
sourced_from: 3-project UI-enhancement prior-art + realized kupiclub worked-examples (668b6c0, F-029)
applies_to: designing or reviewing a UI enhancement (a new/changed user-facing affordance — button, field, step, label, screen) on any consumer app governed by the v2 kernel
---

# UI Enhancement — where a UI delta lives in the v2 model

> **Discipline pattern — strictly NON-NORMATIVE.** This is a reference procedure, not an
> enforced rule. The canonical handbook (CHARTER / AGENTS / LIFECYCLE / QUEUE / GRAPH) and the
> active specs OWN every normative rule. On any conflict — **canonical wins** (mirrors the
> authority boundary of `ux-general-principles.md` / `doc-conventions.md`). It establishes no
> gate, no new mechanism, and no obligation; it tells you where the pieces of a UI change land.

## Problem

A UI enhancement produces several distinct deltas at once — a new affordance, some reusable
scaffolding, and a user-visible label — and it is easy to file all of it as "a spec" or as
nothing at all. Both fail: a spec is for an enforced **rule**, not for a button; and an
undocumented affordance leaves no trace in the graph for a reviewer or a `-C` consumer to find.
Teams then drift on **where** each piece of a UI delta belongs in the v2 model, and the same
question gets re-litigated per screen. The screen-craft rules (how the screen should look and
behave) already have homes — `ux-general-principles.md`, `ux-destructive-operation-safety.md`.
What is missing is the **mapping**: when a UI enhancement lands, where does its delta live?

## Solution — the UI-delta model

A UI enhancement decomposes into three kinds of delta, each with one correct home in the model.
Map each piece before you build; do not collapse them onto "a spec".

### 1 — The affordance is a TASK deliverable + a SCENARIO step — NOT a spec

The affordance itself — the concrete button / field / form step / screen the user touches — is
**work**, not a rule. It lives as:

- a **task** (`tasks/T-NNNN.yaml`) — the unit that builds and lands it through the 9 stages; its
  `expected_touch` names the code/templates changed;
- a **scenario step** (`scenarios/<slug>.md`) — the user-path the affordance participates in,
  narrated zero-normatively and annotated with the governing anchor for each step (SPEC-0076 §5).

Do **not** mint a spec for an affordance. A `spec` homes an enforced **rule** (SPEC-0005
admission: it must assert a rule that could be checked). "There is a Cancel button on the order
screen" is not a rule — it is a deliverable (task) walked by a path (scenario). Reaching for a
spec here is the accretion the anti-complexity filter (CHARTER §Principle 1) exists to stop.

### 2 — Templates + the `covers` edge are the LIVING spec/scenario coverage

Reusable UI scaffolding (shared templates, components, partials) is the durable surface a
scenario actually drives. Connect them with the **`covers` edge**: a scenario's `covers:`
frontmatter lists the code anchors (`<file>` / `<file>#<symbol>`) that user-path drives, resolved
against today's graph anchor-space (SPEC-0076 §4). This `covers` link is what keeps the coverage
**living** — it is queryable (`graph query <scenario>` / reverse-lookup on the anchor) so a
reviewer or a `-C` consumer can ask "what user-path drives this template?" and "is this affordance
still covered?" without reading every screen. Templates without a `covers` edge are invisible to
the graph; the edge is how the enhancement stays discoverable after it ships.

### 3 — Bounded labels have ONE source of truth (SSoT)

Every user-visible **label** (button text, status name, field caption) is drawn from a single
bounded set with one source of truth. Do not inline the same label string across screens, and do
not let two surfaces carry divergent wording for the same concept. A bounded labels SSoT means:
the allowed values live in one place (an enum / a labels module / a single config), and every
surface renders from it. This is the UI analog of the kernel's general "one home, no divergent
copy" discipline (SPEC-0005 rule 8 single-SoT) — a label that exists in two places will drift.

## Procedure

1. **Design** the enhancement against the screen-craft rules — `ux-general-principles.md`
   (three-questions-per-screen, recognition-over-recall, feedback) and, for any destructive
   affordance, `ux-destructive-operation-safety.md`.
2. **File the task** for the affordance (the work unit; its `expected_touch` names the templates
   and code). Build it through the normal lifecycle.
3. **Author / update the scenario step** for the user-path the affordance joins, and add the
   driven templates/anchors to the scenario's `covers:` (the living-coverage edge, SPEC-0076).
4. **Route every label through the bounded SSoT** — add the value to the one source of truth, render
   from it; never inline a second copy.
5. **Review** the delta back against the screen-craft patterns before closing, and confirm the
   scenario `covers` resolves (no dangling anchor).

## What this pattern is NOT

- NOT a gate or a checklist the lifecycle enforces — it adds no stage and no verb.
- NOT a replacement for the screen-craft UX patterns — it sits beside them, answering "where does
  the delta live" rather than "how should the screen look".
- NOT a license to mint a spec per affordance — the affordance is task + scenario, the rule (if any
  genuinely exists) is the only thing that earns a spec.

## See also

- `patterns/ux-general-principles.md` — universal screen-craft rulebook.
- `patterns/ux-destructive-operation-safety.md` — three-layer defense for destructive UI actions.
- `patterns/doc-conventions.md` — when to author a spec vs a pattern vs a task.
- **SPEC-0076** — the scenario node + `covers` edge (`bin/yitc-v2 graph query SPEC-0076`).
