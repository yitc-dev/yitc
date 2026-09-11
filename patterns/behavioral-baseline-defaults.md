---
name: behavioral-baseline-defaults
class: discipline
applies_to: every YITC project authoring user-facing interactions (UI flows, forms, actions) — the named cross-project behavioral/UX-safety defaults a new project should NOT have to re-derive from scratch
---

# Behavioral-Baseline Defaults — the seeded cross-project catalog

## Problem

Every project re-derives the same universal behavioral/UX-safety rules from scratch — and usually
only AFTER an incident teaches it the rule. The kupiclub origin: a cabinet **delete fired immediately
on click, with no confirmation** — an irreversible action with no guard. That class of default
(«destructive/irreversible actions require explicit confirmation») is universal; nothing about it is
project-specific. Re-learning it per project is wasted incidents.

## Solution — name the defaults ONCE, here; let each project FILL + GROW

This catalog **names** the cross-project behavioral defaults. It is the seed of the seed-and-grow
shape (the LOGIC sibling of design-by-default): the kernel names the defaults ONCE; each project turns
the ones it needs into its OWN concrete `specs/` entry (with project-specific values), and **grows**
the catalog when it discovers a new universal default worth seeding back.

This catalog does **not** re-state the deep how-to — that already lives in the general UX patterns. It
is a NAMED INDEX of defaults + the fill/grow/adopt-back protocol. Anti-complexity (CHARTER §Principle 1):
the project-rule machinery already exists (`specs/`); the only added value is **seeding the
cross-project defaults**, not a new rule engine.

## The named defaults

### Default 1 — confirm-before-irreversible (SEEDED, evidence-backed)

Any destructive / irreversible / money action requires an explicit confirmation step before it fires —
never «fire immediately on click». The confirmation states the **concrete consequences**, and the
confirm button is labeled by **result**, not «OK».

- **Evidence:** kupiclub cabinet delete fired immediately on click, no confirm → kupiclub SPEC-0016
  (the project's concrete fill of this default).
- **Deep how-to (do not duplicate):** `ux-destructive-operation-safety` (the three-layer
  confirm / undo / disabled defense + the per-operation matrix) and `ux-general-principles`
  §Error-prevention.

### Candidate defaults (name-only — promote when a project pulls one)

Named but not yet seeded with a worked fill. Each points at the existing pattern that carries the how;
a project promotes one to a concrete spec when it needs it, and the catalog grows the worked default
back when the pattern recurs across projects:

- **loading / empty / error states** — every screen answers «what happens after I act»; no silent
  actions, no blank tables. See `ux-general-principles` §General (empty states, feedback on every action).
- **optimistic-vs-pessimistic writes** — choose per operation: optimistic + undo for small reversible
  writes (soft-delete foundation), pessimistic + confirm for money/irreversible. See
  `ux-destructive-operation-safety` (L1/L2) + `soft-delete`.
- **double-submit guards** — disable the submit control while the request is in flight; idempotency on
  the write path. See `ux-general-principles` §Forms (button states, one toast at a time).

### AI-session behavioral defaults (the owner-communication axis)

The defaults above govern **user-facing interactions** (UI/UX safety). This catalog ALSO names one
**AI-session behavioral default** — how the AI itself behaves when talking to the owner. It is listed here
so the named-default index is one place; its rule-home is elsewhere (named, not restated — CHARTER §P5).

- **offer-audit-adhoc-on-a-structural-pre-plan-fork** (SEEDED, incident-backed) — when the AI presents a
  **structural/design fork that is NOT yet a plan or task**, it OFFERS "check it with the external auditor"
  (`bin/yitc-v2 audit adhoc`) as one of the options, so the owner discovers the auditor consult without
  asking for it by hand.
  - **Scope bound:** structural/pre-plan forks ONLY — NOT routine choices, NOT in-lifecycle gates (the
    Stage-4/8 `audit pre|post` are already mandatory, not an offered option). **OFFERED, never
    auto-fired** — the auditor runs only if the owner takes it, so the audit-loop ceiling (SPEC-0124)
    is untouched.
  - **Rule-home (do not duplicate):** AGENTS-PROTOCOL.md §Recommendation Default — "Default option — offer
    an external-auditor consult on a structural/pre-plan fork".
  - **Evidence:** the owner had to request the auditor consult manually on a structural fork (X-0194).

## How a project FILLS a default (the seed-and-grow protocol)

1. **Fill** — when a project needs a default, author it as the project's OWN `specs/<SPEC>.yaml` (its
   concrete values, surfaces, acceptance). The project spec `cites:` this catalog
   (`behavioral-baseline-defaults`) — that cite IS the consumer-read adoption evidence (CHARTER §P8).
2. **Grow** — when a project discovers a NEW universal behavioral default (not project-specific), add it
   here as a named default / candidate, so the next project inherits it instead of re-deriving it.
3. **Adopt back** — a worked fill that proves general gets its how-to promoted into the relevant general
   UX pattern (`ux-*`); this catalog stays the NAMED INDEX, the patterns carry the depth.

## Review lens

A reviewer checks any change that authors or edits a user-facing interaction against the named defaults
(this is a checklist, not a gate — report, don't block):

- **Irreversible without confirm?** Any delete / cancel / money / irreversible action that fires without
  an explicit, consequence-stating confirmation → flag Default 1.
- **Silent action / missing state?** A write with no loading / success / error feedback, or a list/table
  with no empty state → flag the loading/empty/error candidate.
- **Re-derived, not filled?** A project re-inventing a default this catalog already names instead of
  citing it → point the author at the catalog (the project should `cite:` it, not re-derive).
- **Grown?** A genuinely-new universal default discovered in this change but not added back here → file
  the grow (so the next project inherits it).

## Anti-pattern

- Re-deriving «delete needs a confirm» (or any named default) per project from an incident, instead of
  filling it from this catalog.
- Copying the deep how-to (the confirm/undo/disabled matrix) into the catalog — the catalog NAMES,
  the `ux-*` patterns carry the depth (single home, CHARTER §Principle 5).
- Treating the catalog as a gate/engine — it is a named index + a review lens, never an enforcement layer.

## Cites

- `ux-destructive-operation-safety` (the deep confirm/undo/disabled defense for Default 1)
- `ux-general-principles` (the universal UX rulebook the candidate defaults draw on)
- `soft-delete` (the foundation for optimistic + undo writes)
- Delivery: the at-the-moment `before-authoring-interaction` floor trigger points here (the spec that
  binds it is the catalog's delivery spec; the floor ROW is wired by the requires-ordered follow-up).
- Origin: cross X-0059 (the behavioral-baseline seed-and-grow instance).
