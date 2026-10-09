<!-- GENERATED — identity-agnostic release view of the methodology handbook. Single source; regenerate via `yitc-v2 graph release-view`, do not edit. -->

# GRAPH.md — Specs ↔ Code Graph
<!--AUDIENCE:core-->

Minimal graph. 8 node types, 4 edge types, one query CLI. Bounded by the schema below — additions require anti-complexity check (CHARTER Principle 1).

**The graph is small by intent.** As the spec corpus grows, the SPEC-0005 admission discipline + the anti-complexity check govern — there is no numeric count-gate (see §When to add specs vs just code).

## Schema
<!--AUDIENCE:core-->

### Node types (8)

| Type | Storage | Identifier shape | V1 analog |
|---|---|---|---|
| `spec` | `specs/SPEC-XXXX.yaml` | `SPEC-XXXX` | `RULE-*`, `INVARIANT-*`, `SCN-*` |
| `code` | derived (file paths) | `<file>:<line-range>` | file paths in RULE `implements:` |
| `pattern` | `patterns/<name>.md` | `<name>` | `knowledge/patterns/<name>.md` |
| `plan` | `plans/<slug>.md` + `ideas/<slug>.md` frontmatter (one node type, `kind: plan\|idea`; renamed draft→plan) | `<slug>` | `<v1>/yitc-deferred.md` (planning notes) |
| `rule` | extracted by build script from canonical docs | `rule:<doc-slug>:<section-slug>:<severity>` | `docs/scenarios/artifacts/RULE-*.yaml` (first-class in v1 mature state) |
| `error` | `errors/E-XXXX.yaml` (promotion-only case files) | `E-XXXX` | v1 error-analysis / incident concepts (no first-class store) |
| `scenario` | `scenarios/<slug>.md` frontmatter (`scenario`/`actor`/`status`/`cites`/`covers`, per SPEC-0076) | `<slug>` (the frontmatter `scenario:` key) | `SCN-*` (first-class in v1) |
| `lesson` | `lessons/<slug>.md` frontmatter (`lesson`/optional `status`/`cites`, per SPEC-0090) — per-repo local-craft note | `<slug>` (the frontmatter `lesson:` key) | v1 knowledge notes (no first-class store) |

### Edge types (4)

| Edge | Direction | Source field |
|---|---|---|
| `implements` | spec → code | spec YAML `implements:` field |
| `cites` | any → any (task / decision / spec / scenario → spec / decision / …) — B2 | `cites:` field on task / decision / spec / scenario YAML |
| `defined_in` | rule → doc | rule extraction stores parent doc reference |
| `covers` | scenario → code/anchor | scenario frontmatter `covers:` field (per SPEC-0076 §4) |

All edges derivable from existing structured data. No edge classification beyond these 4; no soft-delete, no versions, no validity layers.

**How each node type earned its place — retrieved (SPEC-0031).** The CHARTER §Principle 1 four-filter
record for the `error`, `scenario` (the `covers` edge) and `lesson` node types, their scope bounds,
and why the schema is this size: SPEC-0031 §Graph schema bounds. Read it before proposing a new node
or edge type — `bin/yitc-v2 graph query SPEC-0031`.

## Schema for specs/<id>.yaml
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0030.** `bin/yitc-v2 graph query SPEC-0030`

## Schema for tasks/<id>.yaml (field catalog in SPEC-0028, repeated cite here)
<!--AUDIENCE:core-->

Tasks reference specs via `cites:` field. Build tool indexes these too — though tasks aren't really «implementing» specs, they cite them as context.

## Build tool + Query CLI + Query layer
<!--AUDIENCE:core-->

> **Retrieved — SPEC-0031.** `bin/yitc-v2 graph query SPEC-0031`

## What graph is NOT
<!--AUDIENCE:core-->

The design fence, in one line: no wider node or edge taxonomy, no validation layer (one narrow
storage-format exception), no unconditional rebuild (the build's result cache), no reactive event
service, no soft-delete or lifecycle store, no history versioning. The full fence is homed in SPEC-0031
§Graph schema bounds — read it before proposing any such addition: `bin/yitc-v2 graph query SPEC-0031`.

If any of above gets requested — anti-complexity filter applies. Most likely answer: «defer until empirical pull».

## What a spec is FOR
<!--AUDIENCE:core-->

A spec is the **primary teaching/design layer for the AI** — not merely anti-drift glue for ≥2
code sites. It tells the agent how the system's logic works, what to analyze before a change,
which rules govern: **rules → code**. Two complementary purposes: (1) teach/design (comprehension),
(2) link + anti-drift (the graph). **`active` is the ONLY normative spec status** — a spec governs
only when `active`; any other status is non-authoritative and cannot satisfy adoption/closure.

## Spec lifecycle
<!--AUDIENCE:core-->

The graph is a top-down **design medium**: a spec change is staged *as a spec* (a `proposed` head)
before code, then reconciled, then activated. Modeled on PEP/ADR proposal-shape — NOT the task-FSM
(authoring a spec is a separate task).

**FSM:** `draft → proposed → active → superseded → retired` (terminal `withdrawn` / `rejected`).

- **`draft`** — exploratory, plan-local: lives in a plan-draft (`spec new --draft --proposed-by <plan>`),
  indexed for plan-local reasoning but **non-authoritative** and EXCLUDED from default
  `graph query --projected`. Authoritative home: SPEC-0005 §4 (`graph query SPEC-0005`).
- **`proposed`** — design-grade, **non-authoritative**: it documents a planned spec/change so the
  graph can show «what will be» (`graph query --projected`, §Query layer). It does NOT govern, and
  **cannot satisfy adoption/closure** (only `active` does — §What a spec is FOR). `proposed` ⇒
  `consumed: false` always (a non-authoritative spec must never be code-consumed).
- **`proposed → active`** is **GATED by an adoption probe** (CHARTER §Principle 3 + 8) — graph
  presence ≠ done. On activation, any `supersedes:` target flips to `superseded` (atomic, one commit).
  **The activation WRITE is performed by `task close` ONLY** (per Part C): closing the spec's
  **`activation_owner_task`** (the single explicit activation carrier — SPEC-0005 §5, the authority; see
  §Schema) flips `proposed → active` as a deterministic closure side-effect, and atomically flips its
  `supersedes:` target (an active target → `superseded`, a still-proposed target → `withdrawn`). The
  owning task is named **EXPLICITLY** in `activation_owner_task`, never derived: **work-first**
  — that field IS the closing task; **plan-born** (`plan stage accepted`, Part B) — the decomposition SETS it to
  the ONE decomposed task chosen to activate the spec (SPEC-0034). `proposed_by` stays
  the PROVENANCE/corpus carrier (the plan slug for plan-born, so the plan's corpus + finalization gate
  keep seeing the spec — §Schema); it is NOT the activation owner. This
  is the **SOLE** writer of `proposed → active`: there is **NO manual `status:` edit and NO parallel/
  ad-hoc activation verb** — a spec found `active` with no activating `task_closed` carrier is a
  drift-#10 / P5 signal. (`spec` has no `activate` subcommand.)
- **`active`** is the single normative status; **`superseded` / `retired`** are non-normative history,
  kept in `specs/` and still indexed.

**Specs may exist before code ( B5):** a `proposed` (or `active`) spec may carry
`implements: []` + a human-visible note. The activation probe still applies.

**Concurrent-change HARD invariant ( B6):** **one active lineage per spec.** Concurrent
`proposed` children of the same spec MUST be either `requires`-ordered (spec-level `requires:`) OR
in a `supersedes:` chain. Two concurrent proposers with neither = **INVALID** — surfaced by the
`multi-proposer-unordered` structural flag in `graph query --projected`. The schema carrier
is spec-level `requires` / `supersedes` + the `activation_owner_task` carrier (SPEC-0005 §5 — the single
explicit activation owner; the ownership VALUE is never in `cites` — cites is informational only, §Schema).
The rule locks now; richer tooling is deferred until an incident pulls it.

## When to add specs vs just code
<!--AUDIENCE:core-->

> **Homed in SPEC-0005** (the spec doctrine) — the admission test (7 criteria + delete-test +
> NOT-a-spec), the governing-parameter rule, and the two-bound volume discipline (anti-oversplit
> merge-default + anti-oversize split-by-surface) live there as **rules 2 + 6** (re-homed from).
> This GRAPH section was a duplicate; per one-home (CHARTER §P5 / SPEC-0005 rule 8) it now points at the
> single home. Read it via `bin/yitc-v2 graph query SPEC-0005` (also fetched before `spec new`). The
> spec count cap is likewise replaced by that admission + two-bound discipline. There is **no numeric
> node-volume trigger** for the other node types either — consolidation is a regular Review judgement on
> observed cost, never a count-gate (counts grow with work; owner directive 2026-06-06). The
> graph-specific node-volume guidance lives with the graph tooling reference — `bin/yitc-v2 graph query
> SPEC-0031`.

## Refs
<!--AUDIENCE:core-->

- CHARTER.md Principle 1 (anti-complexity), Principle 5 (single source of truth)
- LIFECYCLE.md Stage 1 (analysis includes prior-art via `graph query`)

> **Query layer — retrieved (SPEC-0031).** Fetch on demand: `bin/yitc-v2 graph query SPEC-0031`.
