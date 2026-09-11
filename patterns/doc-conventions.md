---
name: doc-conventions
class: discipline
binding: # (AU-5b) — delivered at the Filing + Execution stage-entries (the
  - stage-entry:Filing # stage-delivery axis; folds the retired AGENTS §SHOULD_READ_TASK judgment-
  - stage-entry:Execution # conditional). A PATTERN carrier of the stage-entry token (SPEC-0013).
sourced_from: ad-hoc concept audit 2026-05-28 (decisions/doc-conventions-ad-hoc-audit-2026-05-28.yaml) + owner-directive «structured documentation» 2026-05-28 + V1 prior-art (508 spec artifacts / 22 DPs / 41 policies accretion)
applies_to: creating new V2 documentation artifact — spec (enforced rule, incl. a new standing governance rule — decision new is retired, SPEC-0008) / pattern (cross-project) / handbook section (normative) / task (work unit). Read before Stage 2 Filing or Stage 5 Execution if scope produces new artifact. (The decision corpus is FROZEN history — read-only, not a creatable artifact; see §Naming.)
---

# Doc Conventions — rules for creating structured documentation

> **Discipline pattern.** Recommends structure for new artifacts. NOT normative — canonical
> handbook (the generated `HANDBOOK_READ_ORDER` set) and decision lifecycle
> own normative rules. On conflict — canonical wins (see §Authority boundary).

## When to apply

Apply when creating a new artifact in V2:
- New spec (`specs/SPEC-NNNN-<slug>.yaml` — via `bin/yitc-v2 spec new`), **including a new standing governance rule** (`decision new` is retired — standing rules are authored as specs, SPEC-0008)
- New pattern (`patterns/<slug>.md`)
- New handbook section (rare — additions to the handbook / `HANDBOOK_READ_ORDER` set)
- New task (`tasks/T-NNNN-<slug>.yaml` — via `bin/yitc-v2 task file`)

(The `decision` class is **FROZEN history** — no new `D-NNNN` is authored; existing decisions are read-only and cited by id. See §Naming.)

**Do not apply** when:
- Updating an existing artifact (see §When NOT to create new artifact)
- Mechanical rename / typo fix
- Hygiene fast-path tasks (LIFECYCLE §Hygiene catalog)

## §Artifact taxonomy — type map

The COMPLETE lane-map of every documentation home in V2 — where each kind of note belongs.
Pick the row that matches the note's nature; do NOT conflate lanes (each carries different
lifecycle vocabulary intentionally — CHARTER §Decision lifecycle, QUEUE §State transitions,
LIFECYCLE §9 stages, GRAPH §spec lifecycle).

| Type | Storage | Purpose | When to use |
|---|---|---|---|
| **decision** | `decisions/D-NNNN-*.yaml` | Governance entry — **FROZEN history** (read-only; what and why was decided, historically) | Reference an EXISTING decision by id. **No new `D-NNNN` is authored** — `decision new` retired; a new standing rule → **spec** (SPEC-0008) |
| **spec** | `specs/SPEC-NNNN-*.yaml` | Primary teaching/design layer for the AI + anti-drift link to code | A stable normative surface (rule / invariant / contract / design-boundary / governing parameter) an editor must know before changing the code — admission test in `GRAPH §When to add specs`, NOT gated on ≥2 code sites |
| **pattern** | `patterns/<slug>.md` | Reusable technique / architecture / discipline / **observation** — AND **methodology lessons** (rejected/withdrawn methodological options + the why-rationale, the role orphaned when `decision new` retired; `patterns/methodology-lessons.md`) | Cross-project applicable knowledge, discipline checklist, a settled methodological lesson worth recording so it is not re-litigated, **or a captured research finding / analysis result worth keeping** (`class: observation`) (analog: `big-plan-checklist.md`, `verification-protocol.md`, `methodology-lessons.md`) |
| **lesson** | `lessons/<topic>.md` (markdown + frontmatter, **FILE-PER-TOPIC** — never one bloating file) | A **per-repo, NON-traveling local-craft note** about ONE specific project's specifics — zero-normative REFERENCE (never a rule), the **LOCAL counterpart of a `pattern`** (SPEC-0090). Each repo has its own; never indexed cross-repo | Craft about THAT codebase/product the KERNEL does not need for its own work (e.g. «how kupiclub's monolith splits», «kupiclub's auth quirks»). Boundary test: «does the ENGINE need it for its OWN work?» — general/traveling → **`patterns/`**, local → **`lessons/`**. A «must/always/never» constraint is a drift defect → extract it to a **spec** (SPEC-0090 rule 5). One graph node type, `kind: lesson`; optional `status: retired` only |
| **handbook section** | the generated `HANDBOOK_READ_ORDER` set — enumerated single-SoT at `AGENTS.md` §At-session-start (not listed here; a hand-list drifts) | Normative AI session behavior | Required reading at session start; protocol rules. Subject to the handbook size cap (CHARTER §Principle 2 — authoritative home) |
| **task** | `tasks/T-NNNN-*.yaml` | Work unit | Execution work — code + doc edits per 9-stage lifecycle (LIFECYCLE.md) |
| **plan** | `plans/<slug>.md` (markdown + frontmatter) | Work-in-progress PLANNING with an FSM — **LIFECYCLE §Plan lifecycle owns the state list** (authoritative; not restated here) | Multi-step planning before it is cut into tasks/specs; taken into work only on owner cue (`bin/yitc-v2 plan …`). One graph node type with `idea` (GRAPH §Schema, `kind: plan`) |
| **idea** | `ideas/<slug>.md` (flat note, **NO FSM**) | A **forward-looking implementation seed** — a not-yet-actionable plan-seed held until an incident makes it actionable (AGENTS §Planning artifacts) | You have a concrete future direction (a thing to BUILD/CHANGE later) with no current trigger. **NOT** for research findings / analysis results / scratch — those route **by purpose per SPEC-0091** (the single normative home; see the patterns/lessons boundary note below). Not renamed; one graph node type with `plan` (`kind: idea`) |
| **error** | `errors/E-NNNN-*.yaml` | **Nonconformity case file** — a promoted deviation with RCA (the recurrence-tracking home) | A captured `deviation_captured` is triaged into a durable case file (RCA / pattern / fix). Most deviations stay event-only; promote only on recurrence or material impact (`patterns/error-friction-tracking.md`). Graph node `kind: error` |
| **scenario** | `scenarios/<slug>.md` (frontmatter `scenario`/`actor`/`status`/`cites`/`covers`) | A first-class **user-path** — the owner's primary human-facing working instrument (SPEC-0076) | Capturing/maintaining an end-to-end user journey through the system; queried for coverage integrity via the `covers` edge. Graph node `kind: scenario`, derived status `draft\|building\|live` |
| **MEMORY buffer** | `MEMORY.md` (repo root, single file) | **Non-authoritative, short, read-by-all, consume-once buffer** + bounded temporary instructions — NEVER cited for closure/governance/`from:`; holds no unique durable state (SPEC-0039) | An unmarked short read-by-all to-do-NOW line OR a marked `[instruction]` pointer to a governed provisional. **Short / consume-once / deleted after use** by the session that consumes it — anything that must PERSIST routes by purpose to its durable home (spec / plan / lessons / pattern, SPEC-0091); the handbook + specs WIN on any conflict (P7) |

Each type carries different lifecycle vocabulary intentionally (CHARTER §Decision lifecycle, QUEUE §State transitions, LIFECYCLE §9 stages, GRAPH §spec lifecycle). Do not conflate.

**The patterns(travel) / lessons(local) boundary (SPEC-0090).** Durable CRAFT knowledge splits along ONE decidable axis — **does the ENGINE need it for its own work?** GENERAL YITC methodology / technique / discipline the engine operates by is kernel-authored and **TRAVELS** to every project → **`patterns/`**. Knowledge about ONE specific project's own specifics, which the kernel does NOT need to operate, is **LOCAL** and does NOT travel — each repo has its own → **`lessons/`**. A lesson is the local counterpart of a pattern; both are zero-normative reference notes (an enforceable rule is always a **spec**, never either). This row is **purely additive** — it retires no routing surface; the route-by-purpose lane + read-surfaces + all routing retirements are homed in **SPEC-0091** (the single normative home; per SPEC-0090 §7). This taxonomy row carries no routing-rule TEXT — see SPEC-0091.

## §Internal structure per type

Pattern recommends; templates own normative schema.

**Decision** — **FROZEN history; not authored anew.** `decision new` is retired — a new standing governance rule is authored as a **spec** (see **Spec** above + SPEC-0008), not a decision. The existing decision corpus (`decisions/D-NNNN-*.yaml`, schema in `decisions/_template.yaml`) is **read-only**, cited by id; the historical decision lifecycle (Draft → Accepted → Final | Superseded | Withdrawn, with `adoption_probe` etc.) is recorded at `CHARTER §Decision lifecycle` (retrieved: SPEC-0024) for READING existing entries.

**Spec** — see `GRAPH §Schema for specs/<id>.yaml` and `SPEC-0001` first instance. Fields: `id`, `title`, `status` (active | superseded | retired — `active` is the only normative status), `created_at`, `consumed` (default false; `true` only when code reads a governing scalar from the spec —), `implements:` (durable anchors `<file>` or `<file>#<symbol>`, NOT line ranges —), `cites:`. **No `class:` field** (removed — a spec carries both layers as body sections). Body sections : `## Scenario` (outside-in; omit if purely internal) / `## Internal` (the rule / invariant / contract) / `## Parameters` (optional) / `## Rationale` / `## Verification`.

**Pattern** — see existing analogs `patterns/big-plan-checklist.md`, `patterns/verification-protocol.md`. Frontmatter: `name`, `class` (technique | architecture | discipline | observation), `sourced_from`, `applies_to`. Body: §Problem, §Solution, §Example (real if possible), §Anti-pattern, §Cites — per `PATTERNS.md §Schema`. **Provider-neutral**.

**Lesson** — `lessons/<topic>.md`, the LOCAL counterpart of a pattern (SPEC-0090). REUSES the pattern doc model (markdown + frontmatter), **FILE-PER-TOPIC**. Thin frontmatter: `lesson` slug + optional `status: retired` + `cites` (the node REUSES `cites`, no new edge). **No status FSM** — zero-normative, so no `proposed→active` gate and no currency machinery. Authored ONLY in the repo it concerns (a consumer authors its own; a consumer's distributed `patterns/` is a kernel-owned read-only copy it never edits). `graph build` indexes `lessons/` PER-REPO and rejects only MALFORMED frontmatter (storage-format check, never content/legality).

**Handbook section** — short normative prose. Lines marked `[MUST]` / `[SHOULD]` / `[MAY]` become rule nodes per `GRAPH §Build`. Each addition to handbook subject to anti-complexity 4-filter check (CHARTER §Principle 1). Size budget: the handbook size cap (CHARTER §Principle 2 owns the authoritative number — not restated here to avoid drift).

**Task** — see `tasks/_template.yaml` and `QUEUE §YAML schema`. Allocated via `bin/yitc-v2 task file --title... --class... --scope... --acceptance...`. Required: `id`, `title`, `class` (feature | fix | refactor | docs | infra | hygiene), `priority`, `status`, `scope[]`, `acceptance[]` (with probe per CHARTER §Principle 3), `cites[]`, `requires[]`. Resume contract fields populated on pause: `current_stage`, `resume_from`, `last_verified`, `next_action`, `paused_at`, `paused_reason`.

## §Seed-prose provenance discipline

A per-EDIT **writing** discipline for **always-loaded seed prose** — the `HANDBOOK_READ_ORDER`
handbook set + the floor trigger-map. It applies whenever you AUTHOR or EDIT that prose, and it holds
**notwithstanding §When to apply / §Do not apply above** — those gate whether to *create a new
artifact*, a different axis; this governs *how a seed line is worded* on every touch, including an edit
to an existing file.

**Rule — the current rule, not its history.** Seed prose states the **current rule** and cites the
rule's **HOME** (the spec / decision / pattern that owns it). It does **NOT** carry inline
provenance/amendment-history:

- origin-attribution parentheticals used only to credit who shipped a rule — `(per D-XXXX)` /
  `(per T-XXXX)` / `wired T-XXXX` / `stood up T-XXXX`;
- supersession/amendment clauses — `retired …` / `superseded …` / `amended by …` / `supersedes …`;
- incident-date stamps that only date a rule's origin — `(incident 2026-…)` / `(the 2026-… miss)`.

That history already lives in its durable homes — **git, `decisions/`, spec bodies, the journal** — so an
inline trail is restated history, not the only copy. It costs the always-loaded reader budget (CHARTER
§Principle 2) on every session without teaching the current rule.

**Keep (these are NOT history):** load-bearing SPEC-id pointers that name a rule's governing HOME or its
retrieval — `graph query SPEC-XXXX`, `Full rule: SPEC-XXXX`, a spec id cited AS a rule's home. They are
live navigation, never stripped. When unsure whether an id is history (strip) or a home (keep) → **KEEP**
(fail-closed to anti-Forgetting).

**Enforcement — convention-only.** No behavioral detector / conformance nudge (CHARTER §What V2 is NOT —
no behavioral-discipline detector). The existing report-only `seed-growth` WARN in `graph conformance` is
the only related signal; a provenance-shaped nudge is deferred to an observed re-accretion incident, not
built speculatively. The complementary seed-authoring cue lives at `AGENTS.md` §"Authoring the seed"
(a new rule body lives in its spec; the seed carries a cue + pointer). Motivating strip:.

## §Split-vs-merge — granularity

**Split a spec** in two when (the volume discipline is owned by SPEC-0005 rule 6 — anti-oversplit merge-default + anti-oversize split-by-surface):
- Two genuinely different normative surfaces (rule / invariant / contract) conflated in one body
- Different lifecycle paces bundled

**Split a pattern** in two when:
- Two distinct patterns with overlap < 50% bundled (audit lens: would they cite each other rather than be one?)

**Merge two artifacts** when:
- Same concern split across two files over different incidents (e.g. two patterns on same axis)
- Pattern duplicates ≥ 50% body of existing pattern

**Default — extend existing** (CHARTER §Principle 1 Filter 1). Only split when extension creates dissonance or grows past readability (~350 lines pattern — soft limit; the spec volume discipline is owned by SPEC-0005 rule 6).

## §Edge usage — existing graph edges

V2 graph = 3 edges + 6 node types (GRAPH §Schema — after graph-slim cut : 11→6 nodes, 6→3 edges). Documentation of existing — NOT new mechanism.

| Edge | Direction | Source | When to use |
|---|---|---|---|
| `implements` | spec → code | `spec.implements:` field | Spec enforces rule in named code location(s) — list `<file>:<line-range>` |
| `cites` | any → any (task / decision / spec / scenario → spec / decision / …) | `cites:` field on task / decision / spec YAML | **Informational reference** — non-blocking context |
| `defined_in` | rule → doc | Generated by `bin/yitc-v2 graph build` rule extraction | Rule node points to source handbook section (autogenerated, not authored) |

The `from` / `audited` / `emitted_by` edges were DROPPED by the graph-slim cut (along with their `task` / `decision` / `commit` / `audit_verdict` / `event` node-types — 6→3 edges, 11→6 nodes). Those artifacts keep their own durable stores (`tasks/` · `decisions/` · git history · `decisions/<id>-audit-*.yaml` · `events.jsonl`) — simply no longer mirrored into the graph. The 6 surviving node types: `spec` · `code` · `pattern` · `plan` · `rule` · `error`.

**Task-field dependencies (NOT graph edges per GRAPH §Schema):**

`requires:` field in `tasks/T-NNNN.yaml` lists blocking dependencies (task IDs or decision IDs). Picker excludes task if any `requires:` target incomplete (task: `status != done`; decision: `status != Final`). Specs NOT allowed in `requires:` (use `cites:` per QUEUE §YAML schema). Distinct from `cites:` (informational ref above). Lives in queue model (QUEUE.md), not graph schema (GRAPH.md).

**Syntax examples:**
- Reference decision: `` (short form) or `decisions/-draft-based-doc-lifecycle.yaml` (full path)
- Reference task: `` or `tasks/-codify-doc-creation-conventions.yaml`
- Reference spec: `SPEC-0001`
- Reference handbook section: `CHARTER.md §Principle 2`, `AGENTS.md §audit-contract`
- Reference pattern: `patterns/big-plan-checklist.md`

Both short and path forms accepted in YAML fields. Citation in commit `from:` trailer prefers short form (`T-NNNN` / `D-NNNN`) plus full slug path when ambiguity possible.

## §Naming

**Slug format** — kebab-case, lowercase, non-alnum → `-`. First 50 chars of title typically. Examples: `-draft-based-doc-lifecycle`, `-codify-doc-creation-conventions`, `big-plan-checklist`.

**File paths:**
- Decisions: `decisions/D-NNNN-<slug>.yaml` (FROZEN history — no new D-NNNN is allocated; `decision new` is RETIRED, author new standing rules via `spec new` — SPEC-0008)
- Specs: `specs/SPEC-NNNN-<slug>.yaml` (SPEC-NNNN allocated by `bin/yitc-v2 spec new`)
- Tasks: `tasks/T-NNNN-<slug>.yaml` (T-NNNN allocated by `bin/yitc-v2 task file`)
- Patterns: `patterns/<slug>.md` (no ID prefix — slug is identifier)
- Audit verdicts: `decisions/<task-id>-audit-<stage>.yaml` (per AGENTS §audit-result-schema) or `decisions/<scope>-ad-hoc-audit-<date>.yaml` (per pre-filing snapshot example)
- **Authored records under `decisions/` — name them by SUBJECT, never by task id** :
  `decisions/<subject>-<date>-<kind>.yaml`, e.g. `decisions/spec-0080-remeasure-2026-08-25-finding.yaml`.
  The `decisions/<task-id>-*.yaml` prefix is RESERVED for a card's own audit / consult records (the row
  above), and a card that names its DELIVERABLE that way ships an empty authored-path set, so `audit post`
  refuses to audit the very record it delivered. Rule home: **SPEC-0036** `--zero-ship-diff` row
  (`bin/yitc-v2 graph query SPEC-0036`) — this bullet points at it, it does not restate it.

**ID allocation — always via the allocator verb, NEVER hand-pick an ID:**
- Tasks: `bin/yitc-v2 task file` allocates next T-NNNN, validates schema, emits `task_filed` event
- Decisions: `decision new` is RETIRED (decisions = frozen history — no D-NNNN is allocated); author new standing rules via `spec new` (SPEC-0008). The backlog ops `accept`/`finalize`/`withdraw` are also RETIRED ( — the frozen backlog is fully terminal); `new` (refuse-only) is the sole remaining `decision` subcommand.
- Specs: `bin/yitc-v2 spec new` allocates next SPEC-NNNN (flock-based) + scaffolds from `_template.yaml`
- Hand-allocating an ID by `ls... | tail` is FORBIDDEN — it races under parallel writing sessions and caused the recurring `decision-id-hand-allocated` friction ( incident; N≥2 on 2026-05-30). The verb's `flock` is the single safe allocator.
- The verbs allocate collision-safely; audit-pre still catches any residual path/scope issue ( audit-pre F1 absorption 2026-05-28)

## §Non-goals

Explicit list — preventing pattern's own scope creep over time.

This pattern **does NOT**:
- Introduce new fields in task / decision / spec schemas (templates + GRAPH own schema)
- Define validators, CLI gates, or pre-commit hooks (CHARTER §What V2 is NOT — no hook-laden enforcement)
- Define auto-assembly / composition contract — future composition layer over the graph remains explicit out-of-scope. Tags schema for operation-applicability / topic / severity-routing — **deferred prior-art** (V2 already rejected speculative slots without current consumer)
- Require retrofitting of existing 26 decisions / 17 patterns / 1 spec — applies to **new artifacts only**; existing pulled into compliance organically when touched
- Override normative rules in the handbook (the `HANDBOOK_READ_ORDER` set) / / (see §Authority boundary)
- Mandate new metadata across artifact classes — what exists in templates is canonical; this pattern only references

When future composition layer (or tag schema, or new validator) is proposed — that's a **separate decision** subject to CHARTER §Principle 1 4-filter check. Do not grandfathered through this pattern.

## §Authority boundary

Pattern recommends structure. Canonical handbook owns normative rules.

**On conflict — canonical wins:**

| Conflict | Authority |
|---|---|
| Pattern says X about decision lifecycle; says Y | wins (CHARTER §Decision lifecycle) |
| Pattern says X about handbook size; CHARTER §Principle 2 says Y | CHARTER wins |
| Pattern says X about task schema; QUEUE §YAML schema says Y | QUEUE wins ( normative source) |
| Pattern says X about graph edges; GRAPH §Schema says Y | GRAPH wins |
| Pattern says X about audit contract; AGENTS §audit-contract says Y | AGENTS wins |

**Pattern points at canonical, never reproduces.** Section §Internal structure per type — points at templates and handbook sections, not recreates field lists.

If pattern and canonical drift — capture the dissonance (`deviation_captured`) and resolve via the canonical home: author a **spec** when a new standing rule resolves it (`spec new`, SPEC-0008), or escalate to owner (per CHARTER §Principle 7 Dissonance Is a Question). Pattern updates after resolution.

## §Adoption probe (Principle 3 + Principle 8)

This pattern is infrastructure-class (per CHARTER §Principle 8 — discipline mechanism affecting future artifact creation). Adoption verification required.

**Decision lifecycle for (the decision codifying this pattern):**

- **Draft** — pattern authored, audit-pre absorbed
- **Draft → Accepted** — owner ratifies ( closure event). audit-pre Pass 1 YELLOW absorbed inline, all 3 findings fixed ( ID, lifecycle wording, AC7 regex)
- **Accepted → Final** — **DEFERRED**. Probe: first downstream new artifact (decision / spec / pattern / task) created after commit cites `patterns/doc-conventions.md` AND follows its §Internal structure per type guidance. Verification = state-check (`grep doc-conventions` in next-filed artifact) + manual review (does new artifact actually use the structure?). Separate future task files Accepted → Final transition with probe pass evidence.

Until probe passes, pattern is Accepted-but-not-Final — usable but adoption unverified.

## §Teaching path

`adoption_probe` answers «did this rule LAND + get adopted?». `teaching_path` answers a different
question: «HOW/WHEN does this rule reach the AI's working context?» — the authoring-side complement
to ****'s runtime injection log ( records what was injected + its cost; `teaching_path`
declares the intended delivery surface).

**When to fill** (one line in the governance artifact's `teaching_path:` field — now a **spec**, since standing rules are authored as specs per SPEC-0008; the frozen decision corpus records it historically):
- **Substantive Process / Architectural** rules that change AI behaviour — name the delivery
  surface, ideally a **** injection category, e.g. `MUST_READ_NOW in AGENTS §At-session-start`,
  `template comment, seen on copy`, `patterns/<x>.md surfaced at Stage 1 (SHOULD_READ_TASK)`.
- **Informational / record-only** entries are **EXEMPT** — leave blank (filling it there is the
  ritualization risk this scopes against).

It is **documentary discipline, not a gate** — no validator, no hook, no canonical-handbook growth
(V2 «informs, not enforces», CHARTER §6). First manual instance predates the field:
`patterns/retirement-procedure.md §Discoverability`. External analog: PEP 1 «How to Teach This».

## §When NOT to create new artifact

Counter-weight against accretion (V1 archetype — 508 spec artifacts grew by always creating new instead of extending).

**Prefer updating existing artifact when:**

| Trigger | Action |
|---|---|
| New pattern overlap > 50% body with existing | Extend existing pattern; don't file new pattern |
| New standing rule / spec covers same enforcement axis as existing spec | Update existing spec (`spec edit`); don't allocate new SPEC-NNNN. (A standing rule is never added to a decision — decisions are frozen; rules are specs, SPEC-0008) |
| Handbook insertion extends existing section's topic | Edit existing section in-place; don't add new section header |
| Task scope sub-step doesn't warrant standalone work unit | Inline in parent task scope list; don't file separate T-NNNN |

**Create new artifact when:**

- Genuinely different concern (different lifecycle pace OR different governance axis OR different code surface)
- Existing artifact already covers everything relevant — addition is materially new
- Audit lens check: «would these two artifacts cite each other rather than be one?» → if yes, two artifacts justified

**Default — extend** (CHARTER §Principle 1 Filter 1 «existing analog? extend it, don't create parallel»). Only file new when extension demonstrably wrong.

## Cites

- `SPEC-0008` — new standing governance rules are authored as specs, not decisions (the authoring path this pattern points at; `decision new` retired)
- `SPEC-0005` — the spec doctrine (rule 6 owns the spec split / volume discipline referenced in §Split-vs-merge)
- `decisions/-rejected-ideas-and-backwards-compat.yaml` — prior-art rejecting speculative slots (tags / metadata without consumer)
- `decisions/-pattern-provider-neutrality.yaml` — provider-neutrality extends to patterns/
- `decisions/-draft-based-doc-lifecycle.yaml` — decision lifecycle template and transitions
- `decisions/-instruction-injection-protocol.yaml` — SHOULD_READ_TASK category for this pattern
- `decisions/-provider-session-log-as-durable-citation.yaml` — durable citation rules
- `decisions/doc-conventions-ad-hoc-audit-2026-05-28.yaml` — ad-hoc concept audit verdict + 6 findings absorption
- `CHARTER.md §Principle 1` (anti-complexity 4-filter), `§Principle 2` (documentation-first + handbook cap), `§Principle 3` (Done = Adopted), `§Principle 8` (Adoption Strength), `§Decision lifecycle`
- `AGENTS.md §At-session-start` (this pattern loaded conditionally per SHOULD_READ_TASK)
- `AGENTS.md §Authoring the seed` — the complementary seed-authoring cue (§Seed-prose provenance discipline complements it)
- `` — the Axis-3 provenance strip that motivated the §Seed-prose provenance discipline convention
- `LIFECYCLE.md §Stage 2` (Filing) + `§Stage 5` (Execution) — pointer references
- `GRAPH.md §Schema` (3 edges + 6 node types — read-only source for §Edge usage)
- `QUEUE.md §YAML schema` — read-only source for §Internal structure (task)
- `patterns/big-plan-checklist.md`, `patterns/verification-protocol.md` — discipline-pattern analogs
