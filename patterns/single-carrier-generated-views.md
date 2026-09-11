---
name: single-carrier-generated-views
class: architecture
sourced_from: plan stage-declaration-as-the-single-content-delivery-a (realized 2026-06-04) + SPEC-0033 — distilled as trial run #2 of plan systematic-reusable-craft-lesson-capture-at-closur (Vehicle 3, SPEC-0089)
applies_to: when two or more delivery/routing/content models tangle (deterministic trigger + opaque AI-judgment; multiple prose surfaces enumerating the same routing). Read at Stage-1 Analysis BEFORE adding a model/mechanism to resolve a delivery tangle — the win is usually DELETING a model, not adding one.
---

# Pattern: collapse a tangled delivery into ONE authoritative carrier + generated views, cut over atomically

## Problem

A capability gets delivered by several tangled models at once (e.g. a deterministic action-trigger AND
an opaque AI-judgment path; or several handbook surfaces each independently enumerating the same
routing). The tangle is the cost — drift between the surfaces, ambiguity about which governs. The
tempting "fix" is to ADD a reconciliation mechanism, which deepens the tangle.

## Solution

1. **The win is DELETING the error-prone model, not adding one.** Count the *model + its modes* removed
   (anti-complexity F3), never LOC.
2. **Pick ONE authoritative carrier** — and REUSE an existing entity for it (here: the per-spec
   `binding:` field), never a new one (anti-complexity F1). Every other routing/delivery surface becomes
   a **generated VIEW** of that carrier (the floor-map / verb→spec map are built from it).
3. **Forbid independently-maintained parallel prose** and back the ban with an invariant self-test
   ("no second source per stage-bound action; no handbook section enumerates routing on its own").
4. **Atomic cutover = ONE accept-unit, no broken window:** add the new path + a temporary compat shim +
   strip the legacy in ONE unit, so the live state field is never orphaned; migrate the WHOLE carrier
   corpus in one wave with the build **failing RED on partial coverage** (no silent gaps); migrate docs
   in the same wave (no contradictory interim).
5. **Done = adoption, not presence** — gate closure on a live end-to-end trigger + a real consumer run,
   not "map regenerated / spec active".

## Example

The `binding:` field became the single carrier for "which verb/stage fetches which spec"; the floor
trigger-map + verb→spec map are GENERATED from it (`graph build`), no hand-maintained routing prose; the
cutover landed as one wave with the build red-on-partial-coverage.

## Anti-pattern

- **"Single axis" overreach** — claiming one carrier with no exceptions; name the permitted exceptions
  explicitly (a seed for stage-agnostic verbs, post-action hints, artifact-shaped rules) or the absolute
  claim collapses on the first counter-case.
- **Adding a reconciler** between two tangled models instead of deleting one of them.
- **A partial migration** that leaves some items on the old carrier — the build must fail RED on partial
  coverage, never silently half-migrated.

## Cites

- `SPEC-0033` — the single-content-delivery-axis rule this distils. plan `stage-declaration-as-the-single-content-delivery-a`.
- `patterns/verb-design.md` — the "each verb does its own work" meta-rule this instantiates.
- `patterns/atomic-state-file-writes.md` — the lower-altitude (filesystem) atomicity cousin.
- `SPEC-0089` — the reflection discipline that produced this entry (trial run #2).
