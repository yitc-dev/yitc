---
name: inspection-criteria-roster-portfolio-observation
class: reference
sourced_from: <durable artifact> (SPEC-0120 must-split of patterns/inspection-criteria-roster.md — part 1 re-crossed the one-bounded-read BYTE ceiling at 698 lines / 66360 bytes after the and splits; these two lens-checklists re-home here VERBATIM per SPLIT-never-delete) (the reader extension that makes this possible — bin/lib/inspection.py resolves cadence / weekly-tier / per-theme sections across the DECLARED parts in ROSTER_CRITERIA_PART_SUFFIXES, so a moved theme keeps an honest freshness hash instead of a hollowed one) + SPEC-0120 (durable-doc size governance) + SPEC-0057 (the inspection construct — §3 living-criteria home) + patterns/inspection-criteria-roster.md (part 1 — the roster's resolution origin)
applies_to: PART 4 of the single living inspection home (SPEC-0057) — the freshness-hashed per-theme lens-checklist for T9 (capability graduation & adoption — the kernel↔consumer capability portfolio). `inspect record --theme T9` hashes the T9 section HERE, resolved through the declared-part tuple. Part 1 (`patterns/inspection-criteria-roster.md`) keeps the `CADENCE` values, the operational-hygiene weekly checklist and the T1 / T3 / T7 lens-checklists; part 2 (`patterns/inspection-criteria-roster-run-and-lenses.md`) the run-mode + cross-theme method + foundations + architecture-drift lens; part 3 (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`) the T2 / T4 / T5 lens-checklists; part 5 (`patterns/inspection-criteria-roster-themes-integrity-adoption.md`) the T6 / T8 lens-checklists; part 6 (`patterns/inspection-criteria-roster-real-work-observation.md`) the T10 lens-checklist (moved VERBATIM from here); the umbrella navigation map is `patterns/inspection-criteria-roster-navigation-map.md`. All six parts plus the map are ONE living home split for loadability (SPEC-0120). Provider-neutral by rule (CHARTER §P4b).
---

# Inspection criteria roster — part 4 (the capability-portfolio lens-checklist)

> **What this IS:** PART 4 of the single living inspection home (SPEC-0057) — the freshness-hashed
> **per-theme lens-checklists** for **T9 and T10**, split out of
> `patterns/inspection-criteria-roster.md` (PART 1) under the SPEC-0120 one-bounded-read BYTE ceiling
>. Content is VERBATIM (SPLIT-never-delete): these sections are byte-identical to the ones
> part 1 carried, and `inspect record --theme T9|T10` now resolves and hashes them HERE — the reader
> walks the declared parts, so the `criteria_ref` names this file and hashes THIS text.
> No pointer stub was left behind under a `### T<n> —` heading: one section, one home (a second
> claimant makes the resolver refuse rather than silently hash a stub).
>
> **T10 has since moved on.** When this part crossed the same byte ceiling (687 lines /
> 63,272 B), the T10 lens-checklist moved VERBATIM to **part 6**
> (`patterns/inspection-criteria-roster-real-work-observation.md`) — same section hash, only the path
> a `criteria_ref` names changed. This part now carries **T9** alone; the text below records the
> original move.
>
> **Why THESE two.** The seam is mechanical, not thematic: T9 and T10 are the LAST two sections of
> part 1 and together measure ~15 kB — moving exactly them puts part 1 back under the byte ceiling
> with headroom, while every other part-1 section stays where it is. The test that pinned T9/T10 to
> part 1's filename (`tests/test_t10125_inspection_theme10.py`) is re-pointed at the served-part
> resolver with every assertion kept.
>
> **The other parts:** cadence · operational-hygiene weekly checklist · T1 / T3 / T7 →
> **part 1** (`patterns/inspection-criteria-roster.md`). Run-mode · cross-theme method · foundations ·
> architecture-drift lens → **part 2** (`patterns/inspection-criteria-roster-run-and-lenses.md`).
> T2 / T4 / T5 → **part 3**
> (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`). T6 / T8 → **part 5**
> (`patterns/inspection-criteria-roster-themes-integrity-adoption.md`).
> The umbrella navigation map (check → theme → cadence → how-to-run → rule-home) →
> **`patterns/inspection-criteria-roster-navigation-map.md`**. Each rule these checklists map homes
> elsewhere (cited inline, never restated — P5 / SPEC-0005 rule 8).

## Per-theme lens-checklists (part 4) — the living criteria

### T9 — Capability graduation & adoption (kernel↔consumer capability portfolio)

**Identity.** T9 scans the **capability PORTFOLIO** — the running question «what cross-cutting
capability should the KERNEL offer projects, and what should each PROJECT adopt or build?». It is a
periodic SCAN, not a gate, and it owns ONLY the portfolio *graduate/adopt/local/waive/return*
decision. It does **not** re-run health/reuse/adoption checks — those stay in T6 (operational
integrity), T7 (generalization), T8 (adoption of shipped V2 capabilities); T9 POINTS at them, never
duplicates (guardrail against double-home).

**Hard boundary (CHARTER §6).** The kernel only OFFERS + GRADES a project-declared,
project-owned probe (the SPEC-0110 adapter shape). Container-restart, self-heal, and runtime
ownership stay the PRODUCT's (docker `restart:` etc.) — never a kernel autopilot. Design lineage:
`decisions/kernel-runtime-monitoring-doctrine-audit-adhoc.yaml` +
`decisions/capability-inspection-theme-audit-adhoc.yaml` (both external-audited).

**Two lenses (run the one that fits the checkout):**

- **KERNEL lens — «is candidate X ripe to GRADUATE into an adoptable offering?»** Probe (derived,
  no new store), **two runnable arms, OR-ed — each with its threshold and its disqualifier stated,
  because an arm whose threshold is unstated and an arm whose instrument lies both read as "not
  ripe" exactly like a candidate that was checked** (F-#2 null≠clean):
  - **arm 1 — ≥2 projects hold a divergent LOCAL copy of X.** Instrument, **SCOPE PINNED** (unpinned,
    it silently narrowed: the 2026-09 cycle read 0/10 on three candidates this grep finds in 5, 2 and 9
    projects; `yitc-ops.yaml` alone reproduces the zeros): per registry `yitc_v2` consumer (kernel
    excluded), `git -C <path> grep -ilE '<pattern>' HEAD --. <X>`, X = `':(exclude)events.jsonl'
    ':(exclude)archive/' ':(exclude)*.lock' ':(exclude)*package-lock.json'` — the TRACKED tree at
    HEAD, nothing else excluded at the grep (every other disqualification is the classification below,
    where it shows). The sweep records the pattern and, per project, HEAD sha + RAW matching-file count,
    zeros included — a narrowed scope then reads as a changed count, never a quiet zero —
    **then CLASSIFY the PROVENANCE of every match before counting it, and count a project only for a
    match that is the project's OWN work.** DISQUALIFIED, never counted: kernel-BORN carrier text,
    generated files, and historical `decisions/*.yaml` / `MEMORY.md` prose. **The classification REUSES
    an existing manifest rather than being re-derived by hand every run:** kernel-born carrier text is
    exactly what `graph/born-ops.yaml` holds (the generated born `yitc-ops.yaml` scaffold `init`
    delivers), so a match whose line is present THERE is MECHANICALLY disqualified — the `/rollback/`
    line that produced the false reading below is that manifest's own text. Only matches OUTSIDE the manifest need a
    per-match judgement, and each run makes that judgement afresh and shows its working in the sweep.
    **There is deliberately NO carried-forward classification store** — an inheritance claim would need a
    keyed carrier with invalidation semantics, i.e. exactly the new state the guardrail below forbids, so
    the cost of re-judging the handful of outside-manifest matches is accepted instead. The arm is BOUNDED too: it runs per NAMED candidate under
    consideration, never as a repo-wide sweep, so its cost scales with the candidates being judged, not
    with the corpus. **«Named» has a durable roster, so the bound is a stated limit and not a hole:** the
    candidate set IS the RAW candidate surface below plus whatever a run adds to it, and a capability
    enters that surface by exactly two routes — a PROJECT-lens outcome (c) (a project built X locally and
    raised a `--kind task` pull) or a run adding it. A genuinely new divergent local copy becomes visible through
    the pull signal or through the run that notices it — and through no other route.
    **THE RESULT IS A NAMED SAMPLE, NEVER PORTFOLIO COVERAGE — and a run must say so in those words.**
    This arm does not discover an unnamed capability, and it does not even sweep the whole RAW surface:
    a run probes the candidates it names and REPORTS WHICH ONES IT PROBED. A quiet arm therefore means
    «the probed candidates showed nothing», never «no divergent local copies exist». Reading its silence
    as coverage is the fail-open this paragraph exists to forbid; closing it properly would need a
    deterministic enumerator this theme does not have and does not assume. Without that step the arm manufactures
    ripeness out of the kernel reading its own output back: measured 2026-09-20, a bare
    `/rollback/` grep over the ten consumers returned **10 of 10** and every sampled match was the
    kernel-born SPEC-0094 deploy section — a 100 % false-positive rate on a threshold of 2. This is
    the SAME failure the SPEC-0174 record below names for a key-name grep (X-0851), wired here to
    the instrument that produces it rather than left as a note about one row.
  - **arm 2 — ≥2 NON-TERMINAL `cross request`s of `kind: task` pull for X**, read via
    `bin/yitc-v2 cross inbox` (the `to:me` fold). The threshold is **2** — the same «≥2 siblings»
    bar as arm 1, so the two arms are comparably demanding; `done`/`rejected` rows never count.
  - **arm 3 — SUSPENDED, and that is a reading, not a silence.** The former arm («the <workshop-spec>
    cross-project comparison lens surfaced ≥2 siblings that solved X») has **no instrument**:
    <workshop-spec> is `status: draft` — non-authoritative and excluded from `graph query --projected`
    (GRAPH §What a spec is FOR) — and there is no verb, view or recorded lens output to read. A run
    records it as an explicit `NO-DATA: kernel-lens ripeness arm 3 — instrument absent: <workshop-spec> is
    draft, no comparison-lens output exists`; it is RESTORED as a counting arm only when <workshop-spec>
    goes `active` with a readable output.
  Ripe (either runnable arm clears its threshold) → file the offering as an `adoptable` extension
  (SPEC-0101) or a shared-CODE extraction (X-0205 / SPEC-0122); not ripe → leave on the raw surface.
- **PROJECT lens (run under `-C <project>`) — «do I NEED capability X yet?»** FIVE outcomes, each
  naming the reader that decides it — and **deliberately NOT claimed as one five-way partition**:
  (a)/(w)/(b) are CELL-STATE outcomes over capabilities the kernel already OFFERS, while (c) and (d)
  answer a different question entirely (there is no offering · it is deferred). A measured cell does NOT
  always land in one of the five: a NOT-YET-ACTIVATED or UNRESOLVED cell (see the ACTIVE row's
  applicability trichotomy) is in NONE of them, which is exactly why those buckets are reported
  separately and by name. (The former four-outcome list had no WAIVE outcome while a waiver is the MOST
  COMMON measured state — 21 of the 40 declare-or-waive cells on 2026-09-20 — so a majority of the
  population could not be classified at all, and an unclassifiable cell reads as an unchecked one.)
  - **(a) have it** — `extensions.adopts[]` names the offering in this project's `yitc-ops.yaml`
    → nothing. Reader: the project's own declaration (SPEC-0185 — read the declaration, never a
    hardcoded path or a key-name grep).
  - **(w) waived it** — `extensions.waives[]` names the offering with its reason → nothing, and the
    row is SETTLED, not open. Same reader. **A waiver is an ANSWER**: a project that has weighed the
    capability and declined it is not a portfolio gap, and counting it as one is how a fully-settled
    offering keeps reading as open work.
  - **(b) NO STANCE YET on an offering that applies** → decide: adopt it or waive it. Reader: the
    offering appears in NEITHER list **and** the project's derived SPEC-0198 profile activates that
    offering's dimension. **The label is deliberately «no stance», not «need it»:** absence proves only
    that nobody answered — it is not evidence the project needs the capability, and reading it as need
    is how an inapplicable project becomes a phantom gap.
  - **(c) need it, no kernel offering yet** → build it LOCALLY (product realm) AND raise a
    `bin/yitc-v2 cross request --kind task` pull-signal to the kernel (feeds KERNEL-lens arm 2 above
    — the demand→graduation loop). Reader: the absence of any offering spec for X, plus that
    project's own cross row.
  **WHAT PARTITIONS WHAT — stated so no run can claim more than it measured.** (a)/(w)/(b) are
  EXHAUSTIVE over the **SETTLED-OR-ACTIVATED** cell space: a cell is settled by a DECLARED stance
  (adopted or waived) or, having none, is ACTIVATED and therefore open. **Deliberately NOT called
  «applicable»:** a declared stance settles a cell whatever its applicability — a waiver may itself BE a
  non-applicability judgement — and a run resolves the profile only where it must, i.e. for the cells
  with NO stance. Claiming the settled cells as «applicable» would assert a profile reading the run never
  took. So the denominator a run reports is «settled + activated», and the NOT-YET-ACTIVATED and
  UNRESOLVED buckets sit OUTSIDE it, named. (c) and (d) answer a DIFFERENT question — a capability
  with NO kernel offering at all, and a capability deliberately deferred — so they are NOT cells in that
  space, and a cell-space count must never be presented as covering all five outcomes. A run states the
  readings SEPARATELY and in these words: the **settled-or-activated cell partition**, the
  NOT-YET-ACTIVATED and UNRESOLVED buckets, and whatever (c)/(d) reading it could take.
  - **(d) not yet** → record a parked `return_trigger`. **Reader: NOT-RUNNABLE from the kernel side
    at this cutoff** — `return_trigger` is a field on a parked task in the PROJECT's own `tasks/`,
    and no kernel verb folds sibling projects' parked tasks. A kernel-side run records
    `NO-DATA: project-lens outcome (d) — instrument absent: no cross-consumer parked-return_trigger
    reader`; a run executed UNDER `-C <project>` reads that project's own `tasks/` directly and owes
    no such line.

**No new state (guardrail).** Every T9 signal is DERIVED from an existing mechanism — `cross`
requests, provenance-classified sibling-repo local-copy grep, `yitc-ops.yaml` / `adoptable`
declarations, parked-task `return_trigger`s. T9 adds no store, no status field, no FSM.

**Double-home guardrail — WHERE the line actually falls, and how a run PROVES it held.** «T9 points
at T6/T7/T8, never duplicates» is too coarse to run: T9 unavoidably READS consumer declaration
state, and a reader could call that T8's territory. The line is drawn on the QUESTION, not on the
data: T9 reads a declare-or-waive **CELL STATE** (declared / waived / neither) to decide the
portfolio question *graduate / adopt / local / waive / return* — and STOPS there. **Whether an
adoption actually WORKS** (the shipped capability is invoked, the probe fires, the evidence exists)
is **T8**'s; **whether a local solution should be generalized** into a shared pattern or module is
**T7**'s; **whether the running system is sound** is **T6**'s. A T9 finding that asserts an adoption
is ineffective, or that a capability ought to be generalized, has crossed into another theme and is
ROUTED there, never answered here.
**The guardrail's own probe is SEMANTIC and covers every served part, not a reverse vocabulary grep
of one file.** A run states, for each of T6/T7/T8, the nearest claim that theme makes about the same
surface and why this run's findings do not answer it — naming the part each theme is served from via
`patterns/inspection-criteria-roster-navigation-map.md`, never a hardcoded file. A keyword grep of a
single roster part cannot see semantic duplication and silently omits whichever themes that part
does not serve, so it is not evidence the guardrail held.

**4-filter admission (SPEC-0057 owner-gated new-theme bar; owner directive 2026-07-04).** F1 existing
analog = the inspection roster itself (reused, not a parallel mechanism). F2 view/content, not a new
entity (a theme = a lens-checklist). F3 removed = the «file a plan/card per candidate capability»
escalation (candidates now live on the raw surface until a real pull graduates them). F4 real pull =
the 2026-07-04 owner thread + the grow-on-pull L1/L2/L3 precedent (SPEC-0105/0106/0107→0110).

#### T9 ACTIVE rows (probe-shaped — the only rows an inspection run acts on)

| Capability | Probe (event/state) | Placement | Source-signal | Return / retire |
|---|---|---|---|---|
| Declare-or-waive cells still OPEN on a SHIPPED offering | for each `adoptable` offering **the DERIVED catalog enumerates** (`bin/yitc-v2 graph query extensions-catalog`, filtered to `adoptability: adoptable`; an `internal-only` entry has no adopt-path and is excluded BY DEFINITION, never by omission), count the registry `yitc_v2` consumers naming it in NEITHER `extensions.adopts[]` nor `extensions.waives[]` **AND whose derived SPEC-0198 growth profile ACTIVATES that offering's dimension** — an absent stance on a project the offering does not yet apply to is NOT an open cell | kernel-adoptable — GRADE-only (grades that a stance EXISTS, never which stance) | an offering ships and its APPLICABLE population does not converge on an answer | retire a per-offering entry when its open count reaches 0 (adopted or waived, either settles it) |

**THE OFFERING SET IS ENUMERATED, never assembled from memory.** «For each `adoptable` offering» is
read from the DERIVED extensions catalog (SPEC-0101 rule 2 — recomputed on read from the
`extension:`-marked specs, never hand-maintained), filtered to `adoptability: adoptable`. A run STATES
the enumeration it got and the count, so an offering silently left out of the denominator is visible as
a different count rather than as a clean scan. This closes the sweep's own silent-omission path: a probe
that iterates a remembered list of offerings reads identically whether it covered the catalog or half of
it. `internal-only` entries (a kernel-own tool with no adopt-path) are EXCLUDED by the filter and named
as excluded, not dropped.

**APPLICABILITY HAS A READER — name it, never infer it from absence.** «Applies to» is decided by the
project's **derived SPEC-0198 growth profile**, the same mechanism SPEC-0199 already uses to decide when a
born section's question is ASKED («profile-gated for activation (SPEC-0198 §6): the born stance is a waiver;
the section's question is ASKED... only when the profile dimension that needs it resolves»). A run that
counts an absent stance WITHOUT resolving the profile is reading absence as proof of applicability.

**Applicability is a TRICHOTOMY, and a run REPORTS ALL THREE BUCKETS — it never silently subtracts one.**
SPEC-0198 marks every profile value with HOW it was reached — `(signal)`, `(derived)` or `(default)` —
and that marking, not the value alone, decides the bucket:
1. **ACTIVATED** — the offering's dimension resolves from a `(signal)` or a stated `(derived)` rule to a
   value that activates its question. Only an ACTIVATED cell with no stance is an **open cell**; only
   these are counted by the row.
2. **NOT-YET-ACTIVATED** — the dimension resolves, but to a `(default)` «no signal» value, so the
   question is not yet asked of this project. **A `(default)` is the ABSENCE OF A SIGNAL, never a
   positive finding that the capability will never apply** — so this bucket is REPORTED beside the open
   count with its projects NAMED, never merged into it and never folded away as «not applicable».
3. **UNRESOLVED** — the profile cannot be read at all (no checkout, a resolver error). Recorded as
   `applicability: unresolved`, counted in NEITHER direction, projects named.
A run states all three counts. Reporting the open count ALONE — however it was reached — is the
single-number reading this rule exists to prevent.

**Current reading 2026-09-20, in the three buckets the rule requires (data, re-measured each run, not
criteria — and this is the ONE carrier of the current reading; the graduation records below cite it
rather than restating it):**
**Enumeration this reading ran over (stated, per the rule above):** `graph query extensions-catalog`
returns **6** catalogued extensions, of which **5 are `adoptable`** — SPEC-0094 · SPEC-0162 · SPEC-0164 ·
SPEC-0170 · SPEC-0174 — and 1 is `internal-only` (<workshop-spec>, no adopt-path, excluded by the filter).
5 offerings × 10 consumers = **50 cells**: 16 adopted · 26 waived · 8 without a stance.
- **SETTLED by a declared stance: 42** — incl. SPEC-0094 (5 adopt / 5 waive / 0 open), SPEC-0164
  (6 / 4 / 0) and SPEC-0162 (1 / 9 / 0), each fully settled.
- **OPEN (ACTIVATED, no stance): 6** — SPEC-0170 **3** and SPEC-0174 **3**, in <project> · <project> ·
  <project> (each `surface: public (signal)`). **Whether an ask is outstanding is READ, not remembered:**
  the cross asks these three carry are all TERMINAL (`cross inbox` at this cutoff shows 0
  non-terminal `kind: task` rows; every `task`-kind row reads `done`). So the earlier «a LIVE ask is
  open, nothing further is owed» reading no longer holds on the data — these are open cells with no live
  ask behind them, and what is owed is the project's stance, which only that project can give.
- **NOT-YET-ACTIVATED: 2** — <project> × {SPEC-0170, SPEC-0174}: `surface: unknown (default)`, a library
  with no public surface. Its first public route flips these to OPEN with no edit here.
- **UNRESOLVED: 0.** · SPEC-0164 **0** and SPEC-0162 **0** no-stance cells, so no applicability question
  arises for them.

> **Why this table has ONE row where it had two (2026-09-20 fold).** Both prior rows —
> «Runtime error alerting (500s / exceptions)» and «Backup restore-DRILL» — had MET their OWN
> `Return / retire` conditions and were still being scanned as open portfolio gaps. Measured: the
> alerting row said «retire when an offering exists + adopted» — SPEC-0164 is `active` and its cells
> read 6 adopt / 4 waive / **0 open**; the restore-drill row said «retire when the drill's freshness
> is graded by the SPEC-0110 monitor + adopted» — SPEC-0162 is `active` in exactly that grade-only
> shape and its cells read 1 adopt / 9 waive / **0 open**. Both are RETIRED into the graduation
> records below, by the same route the «Frontend availability / uptime» row took. Their replacement
> is the row above, which is the GENERAL form of what both rows were actually watching (an offering
> whose population has not yet answered) — so the table keeps measuring a live question instead of
> two settled ones, and a future graduation retires an ENTRY in its reading rather than needing the
> row itself rewritten.

- **G7 — waiver premise vs profile:** each waiver's premise is re-checked against the derived profile; a born placeholder is not an answer — `bin/yitc-v2 -C <repo> --read-only profile` + `bin/yitc-v2 nightly`.

#### T9 RAW candidate surface (idea-pool — NO obligation; each tagged; promote to an ACTIVE row only when a probe exists)

Tags: `existing-pointer` (already an offering — see the cited spec) · `kernel-adoptable` (candidate
offering) · `product-local` (project-only, kernel does not offer) · `other-theme` (belongs to T6/T7/T8).

**Graduation records (RECORD-ONLY — an `existing-pointer` capability already born in the kernel; no
new mechanism).** A row promoted to `existing-pointer` because the offering already ships gets a
one-line record here naming its adopt path + adoption/conformance probe — not a new detector (each
cited spec keeps its own anti-detector stance):

- **Consumer provider-neutral context-home + thin vendor adapter → SPEC-0125** (owner
  directive 2026-07-10, RECORD-ONLY). **Adopt path:** `bin/yitc-v2 -C <project> init` unconditionally
  stands up the thin vendor adapter + populated neutral project-context home (the `consumer_init` born
  event; impl `bin/lib/init.py#_ensure_consumer_vendor_adapter`) — mandatory-born, not opt-in.
  **Adoption/conformance probe — WITH its denominator, which the trail alone does not carry:** the
   rollout wave (done, resolves X-0163/X-0164) — conformance cross trail **X-0291..X-0294**
  (<project> / <project> / <project> / <project>: thin adapter VP1-clean + populated neutral
  home VP2-met). That trail names **4** projects; the population is **10**. Re-measured 2026-09-20
  across all ten registry `yitc_v2` consumers: **10 of 10** carry a thin vendor adapter (`<vendor-adapter>.md`
  14–19 lines) AND a populated neutral home (`CHARTER.md` and/or `AGENTS.md`) — so the state is
  clean, but a reader of the trail alone would have taken 4-of-10 coverage for complete (M8: presence
  is not absence). State the denominator with the trail, as the SPEC-0174 record below does.
  SPEC-0125's declined drift-detector/lock stance stands — no conformance mechanism is added here
  (this is a pointer, not a gate).

- **Runtime error alerting (500s / exceptions) → SPEC-0164** (fold 2026-09-20,
  RECORD-ONLY — **RETIRED from the T9 ACTIVE rows above by that row's own `retire when an offering
  exists + adopted` condition, now MET**). **Adopt path:** declare the incident sink and who acts on
  it in `alert_routing:`, citing SPEC-0164 in `extensions.adopts[]`, or waive it there with a reason;
  grade-only — the kernel grades that a stance exists, never the sink's quality (SPEC-0164). The
  ADJACENT frontend-error conveyor SPEC-0170 (the consumer session-start echo SPEC-0171) is a
  DIFFERENT offering in the same family and is NOT retired — it still carries open cells (see the
  ACTIVE row's reading). **Adoption/conformance probe, denominator stated:** all **10** registry
  `yitc_v2` consumers, re-measured 2026-09-20 from each project's OWN declaration — **6 declared**
  (<project> · <project> · <project> · <project> · <project> · <project>) · **4 waived**
  (<project> · <project> · <project> · <project>) · **0 open**.

- **Backup restore-DRILL → SPEC-0162** (fold 2026-09-20, RECORD-ONLY — **RETIRED from the
  T9 ACTIVE rows above by that row's own `retire when the drill's freshness is graded by the
  SPEC-0110 monitor + adopted` condition, now MET**). **Adopt path:** declare the drill's cadence +
  freshness probe in the SPEC-0110 shape and cite SPEC-0162 in `extensions.adopts[]`, or waive it.
  GRADE-only, and the boundary the retired row insisted on is UNCHANGED by graduation. **The
  freshness-grading half of the retire condition is carried by CLAUSE, not inferred from the title** —
  SPEC-0162 §Scenario, verbatim: «the kernel **GRADES the drill's freshness** — how long ago the drill
  last passed — and alerts when it goes stale or was never run. The kernel NEVER runs the drill (that
  stays operator-owned); it only grades the last-run age, exactly the SPEC-0110
  grade-only shape.» That is the SPEC-0110 monitor grading the retired row demanded, in the offering's
  own words; an `active` status plus an adoption alone would NOT have established it. **And the grader is
  evidenced RUNNING, not merely specified** — the adopting project's declared freshness adapter, invoked
  read-only 2026-09-20, returns among its pipelines: `{"name": "restore_drill", "state": "stale",
  "age_hours": 1083.85, "detail": "last output 1083.85h ago (SLA 336h)"}`. The grader evaluates last-run
  age and produces the stale-or-never-run result the retirement condition names. **That reading is also a
  live portfolio fact, not only a proof:** the one project that adopted the drill is currently STALE
  against its own 336h SLA — precisely the signal the graduated offering exists to surface, and the
  ADOPTING PROJECT's to act on, never the portfolio scan's (T9 reads the cell, never the remedy). **Adoption/conformance probe, denominator stated:** all **10** consumers, re-measured
  2026-09-20 — **1 declared** (<project>) · **9 waived** (the other nine) · **0 open**. A 1-of-10
  adoption is a SETTLED portfolio question, not a thin one: nine projects answered «not for us» with
  a reason, which is outcome (w) of the PROJECT lens, not an open cell.

- **Frontend availability / uptime → SPEC-0174** (validate pass 2026-08-25, RECORD-ONLY —
  RETIRED from the T9 ACTIVE rows above by that row's own `retire when graduated to an adoptable
  extension` condition, now MET). **Adopt path:** declare a `freshness:` section whose adapter probes
  the live HTTP surface, carrying the MANDATORY `freshness.reachability.target` naming the address it
  reaches (SPEC-0110 rule 6), and cite SPEC-0174 in `extensions.adopts[]`; a project with no live
  edge WAIVES in `extensions.waives[]` with a forward-aware reason. Grade-only — the kernel never
  issues a request of its own (SPEC-0174 rule 2). **Adoption/conformance probe:** the rollout
  (done) — one cross ask per consumer, trail **X-0645..X-0653**; three consumers landed an adoption.

  **VALIDATED classification — all TEN registry `yitc_v2` consumers, each read from its OWN declared
  shape in `<project>/yitc-ops.yaml`.** Note the DENOMINATOR MOVED: this row was filed
  against NINE projects; <project> was registered as a first-class consumer afterwards, so the
  population is ten.
  - **Declared (3)** — `extensions.adopts[] spec: SPEC-0174` + `freshness.reachability.target`:
    <project> (`https://<project-domain>/api/v1/health`, plus the `*/15` host cron
    `product_cron.host_crons[<project>-edge-availability]`) · <project>
    (`https://<project-domain>`) · <project> (`http://<ip>:8002/health`).
  - **Waived (3)** — explicit `extensions.waives[] spec: SPEC-0174`, forward-aware reason: <project>
    (waive is about VALUE not applicability — live edge, deploy seam covered by the adopted SPEC-0094
    `live_probe`, no unnoticed-outage incident; owner waive 2026-08-13, X-0645) · <project>
    (X-0646) · <project> (X-0650).
  - **No stance (4) as of 2026-08-25** — `extensions:` section PRESENT with a `waives:` list but NO
    SPEC-0174 entry in either list: <project> (X-0647) · <project> / <project> (X-0648, a real UI +
    live deploy) · <project> (X-0651) · <project> (X-0653). **That is this record's HISTORICAL reading
    and it stays as filed. For the CURRENT split of those four, read the ACTIVE row's current-reading
    block above — the single carrier — which resolves them under an applicability reader this record
    predates; it is not restated here, so the two can never drift.**

  **The key-name grep does NOT reproduce this result, in EITHER direction — it is why this row was
  filed at candidate grade (X-0851 precedent).** `grep -ic uptime` over the whole of each consumer's
  `yitc-ops.yaml` gives <project> 2, all others 0. Both of <project>'s lines are PROSE inside an
  `alert_routing:` comment stating «THIS IS NOT EXTERNAL UPTIME MONITORING» — not a declaration; and
  the nine «misses» conceal three adoptions and three explicit waivers. No `uptime:` carrier exists
  anywhere: no SPEC-0093 concern declares a `section:`/`carrier_path:` of that name, so the literal
  key could never have been the answer. Read each project's declared shape; never the key name.

- **Runtime health & availability:** container health + restart-policy declared `kernel-adoptable`;
  TLS cert-expiry `kernel-adoptable`; host resource watch (disk/mem/inode) `kernel-adoptable`
  (near SPEC-0105/0111); upstream-dependency reachability (external APIs / DB) `kernel-adoptable`;
  queue/worker liveness `product-local`; external-API rate-limit/quota headroom `product-local`.
- **Data & jobs:** data/output freshness `existing-pointer` (SPEC-0110); cron/scheduled-work
  governance `existing-pointer` (L2, in-flight plan); data-integrity / schema-drift `product-local`;
  DB-migration discipline `product-local`; retention / data-lifecycle `existing-pointer` (SPEC-0199
  `data_obligation:` — retention + deletion-on-request are a born declare-or-waive section).*
- **Errors & observability:** log retention/aggregation `kernel-adoptable`; runtime error alerting
  `existing-pointer` (SPEC-0164, record above — its §Scenario: «when something breaks here, WHERE does
  the alert go — and WHO reads it and acts? It declares the two together in its `yitc-ops.yaml`
  `alert_routing:` section, or it waives with a reason») and frontend-error triage `existing-pointer`
  (SPEC-0170 §Scenario: «a cadence sweep folds it by fingerprint, recurrence collapses the noise, and
  only what survives the thresholds becomes a CONFIRMED cluster the owner is shown» + SPEC-0171, its
  consumer session-start echo); telemetry/analytics wired `product-local`; tracing / request-id propagation `product-local`; SLO/SLA tracking `product-local`.
- **Security & deps:** secrets declaration + rotation reminder `kernel-adoptable`; dependency pin /
  lockfile / update cadence `existing-pointer` (SPEC-0199 `dependency_cadence:` — the one section
  asked of every project, prototype included)* and, SPLIT from it (another carrier), CVE / advisory
  SCANNING `existing-pointer` (<workshop-spec> rule 6 — `bin/security-audit` CHECK 4, init-seeded — + the
  SPEC-0163 §4a land floor, project `verify.floor.dependencies.command` additive). Open question is
  ADOPTION (project lens): registry sweep 2026-09-23 — 3 of 10 consumers declare that command, 7 do not
  (<project> · <project> · <project> · <project> · <project> · <project> · <project>; three
  of them run their own pip-audit in a Dockerfile); auth/authz baseline `other-theme`/doctrine (X-0205 shared
  PATTERN); access-audit / least-privilege `product-local`; pentest cadence `product-local`;
  supply-chain / lockfile integrity `product-local`.
- **Build & quality (UI):** UI baseline / design-system `existing-pointer` (SPEC-0093 `ui.baseline` +
  SPEC-0100); test taxonomy `existing-pointer` (SPEC-0093 `tests.classes`); perf/bundle budget
  (Lighthouse) `product-local`; accessibility `product-local`; visual-regression `product-local`;
  i18n/l10n `product-local`; SEO/meta `product-local`.
- **Ops & deploy:** deploy smoke gate `existing-pointer` (SPEC-0094); rollback-rehearsal cadence
  `kernel-adoptable`; canary/blue-green `product-local`; feature-flag discipline `product-local`;
  environment parity (staging≈prod) `existing-pointer` (SPEC-0199 `environments:` — config-source +
  staging/prod parity stance).*
- **Cost & capacity:** cloud/API spend monitoring `existing-pointer` (SPEC-0199 `cost:` — the spend
  threshold at which spend becomes a task, plus where the number is read)*; capacity/scaling headroom
  `product-local`.
- **Reuse & shared code:** shared-CODE extraction `other-theme`/doctrine (X-0205 + plan
  `extract-the-<project>-system-into-a-shared-cro`); cross-project engineering-knowledge exchange
  `other-theme` (idea `engineering-knowledge-exchange-between-projects`); shared-PATTERN promotion
  `other-theme` (T7/SPEC-0090 lesson-generalization).
- **Docs & onboarding:** operational RUNBOOK (logs / rollback / contact) `existing-pointer`
  (SPEC-0199 `runbook:`)* and, SPLIT from it, README CURRENCY `product-local` (no offering covers
  whether a README is current); per-project onboarding runbook `product-local`; API/contract docs `product-local`; consumer provider-neutral project-context home
  + thin vendor-adapter (thin `<vendor-adapter>.md` → neutral home) `existing-pointer` (SPEC-0125).
- **Auditor-added families (2026-07-04):** incident/alert routing `existing-pointer` (SPEC-0164 —
  the SAME offering as the runtime-error-alerting record above, which it was double-listed against as a
  candidate. The mapping is the offering's OWN scope, not an inference from its title: SPEC-0164
  §Scenario declares WHERE an incident alert goes AND WHO acts on it, and «the kernel grades that the
  STANCE is present and complete, exactly the SPEC-0110 grade-only shape» — which is what this candidate
  named. The kernel still never SENDS the alert; routing stays operator-owned, so the tag says an
  offering exists, never that the routing is done); DNS/domain expiry `kernel-adoptable`; config/env CONFIG-SOURCE +
  staging-parity STANCE `existing-pointer` (SPEC-0199 `environments:`, which declares `config_source:` +
  `staging:`)* and, SPLIT from it, actual config/env VALIDATION `kernel-adoptable` — declaring WHERE
  config comes from is not VALIDATING it, and no offering checks a config's correctness; API
  contract/versioning `product-local`; PII / data
  classification `existing-pointer` (SPEC-0199 `data_obligation:` `classification:`).*

*\* Re-tagged by the 2026-09-20 fold against the G14 production-readiness family —
SPEC-0199 (five born declare-or-waive sections: `environments:` · `data_obligation:` · `cost:` ·
`dependency_cadence:` · `runbook:`) with SPEC-0198 deciding WHEN each is asked. Every re-tagged row
had carried `product-local` («project-only, kernel does not offer») or `kernel-adoptable`
(«candidate offering») for a capability the kernel had ALREADY shipped — a tag that makes a
positive, and false, claim about the kernel. THREE rows were SPLIT rather than re-tagged, because the
offering covers only PART of what the row named: dependency CADENCE is offered while CVE SCANNING
rides another carrier (<workshop-spec>/0163 — re-tagged 2026-09-23), an operational RUNBOOK is offered while README CURRENCY is not, and a config-SOURCE/staging stance
is declared while config VALIDATION is not — re-tagging any of them wholesale would have retired a real
gap by arithmetic. The test a re-tag must pass is stated so it can be applied again: cite the carrier's
OWN clause and check it covers the WHOLE capability the row names; where it covers only part, SPLIT.*

