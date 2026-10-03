---
name: inspection-criteria-roster-themes-delivery-outcome-adoption
class: reference
sourced_from: <durable artifact> (SPEC-0120 must-split of patterns/inspection-criteria-roster.md — part 1 re-crossed BOTH one-bounded-read ceilings at 914 lines / 82867 bytes after the and splits; these five lens-checklists re-home here VERBATIM per SPLIT-never-delete) (the reader extension that makes this possible — bin/lib/inspection.py resolves cadence / weekly-tier / per-theme sections across the DECLARED parts in ROSTER_CRITERIA_PART_SUFFIXES, so a moved theme keeps an honest freshness hash instead of a hollowed one) + SPEC-0120 (durable-doc size governance) + SPEC-0057 (the inspection construct — §3 living-criteria home) + patterns/inspection-criteria-roster.md (part 1 — the roster's resolution origin)
applies_to: PART 3 of the single living inspection home (SPEC-0057) — the freshness-hashed per-theme lens-checklists for T2 (instruction↔doc fidelity + delivery/readiness), T4 (outcome / cost-effectiveness) and T5 (meta-loop health); the T6 (operational integrity) and T8 (adoption) lens-checklists moved VERBATIM to part 5 (`patterns/inspection-criteria-roster-themes-integrity-adoption.md`). `inspect record --theme T<n>` hashes each section HERE, resolved through the declared-part tuple. Part 1 (`patterns/inspection-criteria-roster.md`) keeps the `CADENCE` values, the operational-hygiene weekly checklist and the T1 / T3 / T7 lens-checklists; part 4 (`patterns/inspection-criteria-roster-portfolio-observation.md`) the T9 lens-checklist; part 6 (`patterns/inspection-criteria-roster-real-work-observation.md`) the T10 lens-checklist; part 2 (`patterns/inspection-criteria-roster-run-and-lenses.md`) the run-mode + cross-theme method + foundations + architecture-drift lens; the umbrella navigation map is `patterns/inspection-criteria-roster-navigation-map.md`. All six files are ONE living home split for loadability (SPEC-0120). Provider-neutral by rule (CHARTER §P4b).
---

# Inspection criteria roster — part 3 (the delivery, outcome & meta-loop lens-checklists)

> **What this IS:** PART 3 of the single living inspection home (SPEC-0057) — the freshness-hashed
> **per-theme lens-checklists** for **T2, T4 and T5** (T6 and T8 moved on to **part 5**,
> `patterns/inspection-criteria-roster-themes-integrity-adoption.md`), split out of
> `patterns/inspection-criteria-roster.md` (PART 1) under the SPEC-0120 one-bounded-read ceiling
>. Content is VERBATIM (SPLIT-never-delete): these sections are byte-identical to the ones
> part 1 carried, and `inspect record --theme T<n>` now resolves and hashes them HERE — the reader
> walks the declared parts, so the `criteria_ref` names this file and hashes THIS text.
> No pointer stub was left behind under a `### T<n> —` heading: one section, one home (a second
> claimant makes the resolver refuse rather than silently hash a stub).
>
> **Why THESE themes.** The seam is mechanical, not thematic: part 1 keeps every section a test pins
> to *its* filename — the `CADENCE` block and weekly tier (`tests/test_review_due.py`), T3
> (`tests/test_t10935_…`), T7 (`tests/test_t10027_…`), and the T1
> note whose part-1 text `tests/test_t11049_…` scans — and part 3 takes the rest. Moving anything
> else would have meant editing a pinned test to follow the content.
>
> **The other parts:** cadence · operational-hygiene weekly checklist · T1 / T3 / T7 →
> **part 1** (`patterns/inspection-criteria-roster.md`). T9 → **part 4**
> (`patterns/inspection-criteria-roster-portfolio-observation.md`). T10 → **part 6**
> (`patterns/inspection-criteria-roster-real-work-observation.md`). T6 / T8 → **part 5**
> (`patterns/inspection-criteria-roster-themes-integrity-adoption.md`). Run-mode · cross-theme method · foundations ·
> architecture-drift lens → **part 2** (`patterns/inspection-criteria-roster-run-and-lenses.md`).
> The umbrella navigation map (check → theme → cadence → how-to-run → rule-home) →
> **`patterns/inspection-criteria-roster-navigation-map.md`**. Each rule these checklists map homes
> elsewhere (cited inline, never restated — P5 / SPEC-0005 rule 8).

## Per-theme lens-checklists (part 3) — the living criteria

### T2 — Instruction↔doc fidelity + delivery/readiness

- **Surfaces:** entry skill `<provider-config>/commands/yitc.md` (project-local SoT) + AGENTS
  §startup/§after-compact + `session start` echo + worktree-creation instruction + thin-pointer
  expectation + the injection read-order + stage-bundle axes + must-read gates +
  MEMORY.md instruction-kind + **the MCP session-start reconcile delivery** (SPEC-0118 /
  `patterns/working-with-mcp-in-v2.md` §session-start reconcile + the `before-mcp-use` floor-map row —
  a `binding:[seed]` `session start` echo that a `/compact` evicts, so its re-derivation is itself a
  T2 delivery surface) + **the carried delivery deltas** (undated — each
  stays a surface until retired, never until the next cycle): the `session context` threshold echo +
  refresh hand-off re-delivery + `session handoff list` re-fold (SPEC-1004/0115), onboarding stations as consume-receipted delivery
  (SPEC-0147 — seeded vs consumed), worker-seed CHAIN completeness (SPEC-0127 — «one part is not the
  seed»: part 1 names all parts AND each exists), and the `debt` echo re-fold (SPEC-0119) + **the
  OUT-OF-BAND delivery surface**: an obligation delivered ONLY in the dispatched-Worker launch
  preamble (`bin/lib/dispatch.py`) and on NO re-readable surface — a Worker's post-`/compact`
  restoration IS its seed chain, so a preamble-only rule is simply GONE (measured 2026-09:
  SPEC-0191's block-classification ladder, SPEC-0180's over-cap held-turn land exit, SPEC-0204's
  ceiling halt VERB) — and the seed's own **citation currency** (every `SPEC-NNNN` the always-loaded
  seed cites resolving `active`, or framed as history).
- **Probes:** **DIFF each instruction against the LIVE canon + implementation — «I read it» is NOT a
  fidelity probe** (the entry skill is a KNOWN re-staleness node, N≥3 — check it EVERY run); completeness
  not match; **delivery «worked»** — three-column reconcile promised↔journal↔log (consume ≥3 paths:
  graph query / Read / raw sed-cat; «no event» ≠ «not delivered»); **readiness mechanically** — the
  require-reads gate (SPEC-0050, emits `read_gate_refused`; kinds read-check / stage-correspondence /
  verification-exists per SPEC-0059) — **feeding-view: `bin/yitc-v2 graph query discipline-ratio`**
  (refusal numerator split BY kind over `cli_invoked`; SEPARATE ratio per kind, never one mixed);
  capture the AGGREGATE pattern and read it by **CONCENTRATION, never magnitude** — a
  delivery-redesign signal is refusals CONCENTRATED on ONE contract/verb; a large count
  spread broadly across many verbs is the gate WORKING AT SCALE and is a READING, not a finding (in
  2026-09 pass 1 the two tracks read the SAME by-verb table oppositely — 714/702/470 across 11+ verbs
  — because this discriminator was unstated). A single refusal is likewise the gate working;
  **report ONE finding PER unre-delivered item, never one bundled finding per reconcile** (same run:
  the primary bundled three seed-echo items, the external split them — same data, different sets, an
  unstated unit); and a delivery curve with **no due-obligation denominator** (a flat consume count
  over a window in which nothing was due) is a READING, not a finding — M8 presence≠absence on the
  delivery axis; **MCP reconcile/floor
  delivery (SPEC-0118)** — the session-start reconcile (list connected → compare vs the declared
  standing set → disable extras) AND the CONNECT/USE `before-mcp-use` floor row are both DELIVERED
  surfaces: check the START echo, the floor-trigger-map row, and the post-`/compact` re-derivation
  pointer (AGENTS §After-/compact MCP reconcile re-delivery) all resolve to SPEC-0118 /
  `working-with-mcp-in-v2.md` and are not stale (a KNOWN co-design-coherence node per SPEC-0007 §5b).
- **Method/evidence-grade:** mark each finding promise-level (promise text ⊂ canon text, grep-provable)
  OR consumption-level (journal/log proves the miss) — NEVER mix (mixing gives false refutations);
  flag **framing-misclassification** — a non-`active` rule presented in instructions as a live
  principle — with its MECHANICAL instrument, never by eye: resolve EVERY `SPEC-NNNN` the
  always-loaded seed cites against `specs/*.yaml` `status:`, then read the FRAMING of each non-active
  hit (explicitly historical — «supersedes X», «historical origin X» — is CLEAN; cited as a live
  authority is the defect; 2026-09: 6 non-active ids cited, 1 misframed). It is a defect BEYOND
  staleness and carries a **HIGH severity floor** when the misframed citation is an AUTHORITY or
  ESCALATION pointer — the clause that tells the AI whose call something is cannot itself be
  non-normative; ABORT-fallback = inline file excerpts into the prompt. Router hygiene
  (F-g2): global <vendor-adapter>.md size/whitelist (≤~40 lines), redirect rule present AND obeyed, no
  re-accretion (durable-form guard = external territory — route on the gate).

- **G2 — stated-cwd resolution:** every command in /start, the session echo and its pointers resolves from its STATED cwd; echo self-attestation is checked against receipts; the read-only echo is exercised — `bin/yitc-v2 -C <repo> --read-only session start` vs `bin/yitc-v2 journal query --type seed_read`.

### T4 — Outcome / cost-effectiveness (context-economy)

- **Surfaces:** production usage; effort volume + trajectory; friction/rework; token/cost. (`M6/M7`
  REMOVED 2026-09-20 — no probe.)
- **Probes — each names its DIRECTION of good and its BOUND, or it is declared CONTEXTUAL.**
  **INVENTORY (rule A) — 15 sweep sections, this order, all opened BEFORE any probe runs:** 1 P6 seam
  read amplification · 2 P7 verify waste · 3 audits/done + RED share + GREEN-first % · 4 verify-cost
  feed (`verify_metrics`) · 5–9 context-economy P1–P5 · 10 production adoption + external `from:` ·
  11 closures/day · 12 friction/done · 13 inter-stage elapsed · 14 threshold arms · 15 DROP-but-FLAG.
  A probe whose instrument does not exist carries the exact line `NO-DATA: <probe> — instrument
  absent: <instrument>` (none stands today: P5 and threshold arm 2 were RETIRED to kind (a)).
  **Production adoption** (CONTEXTUAL, not graded; direction declared, no bound) — over the REGISTRY
  universe, the DENOMINATOR for both shares is kernel closures PLUS `task_closed` rows from READABLE
  non-kernel registry projects. Production share = the readable non-kernel closures over it, a LOWER
  bound; kernel share = kernel closures over it, an UPPER bound Direction: production UP, kernel
  DOWN. A READ/NOT-READ census names each reason (11 of 24 unreadable 2026-09-20). NO batched
  registry-wide collector exists: the census is a BOUNDED per-project read over the registry roster,
  recorded here rather than rediscovered each run. External `from:` is a CONTEXTUAL SHARE (no
  direction, not graded): realm-external trailers ÷ all closure trailers in the window, classified
  by REALM — target repo is not this one — never by artifact kind. **closures/day trajectory**
  (KERNEL-ONLY — the registry census belongs to production adoption; direction: up; CONTEXTUAL, no
  bound) — REPLACES commits/day (bookkeeping, not delivered change). Bucket `task_closed` ts in UTC;
  zero-closure calendar days are COUNTED in both the mean and the median; assert active-days ≤
  window. **audits/done · RED share · GREEN-first %** (direction: down · down · up; WARN on a
  >10-POINT window-over-window move for the two PERCENTAGES, and when the ABSOLUTE
  window-over-window delta of the RATIO exceeds **0.5 audits/closure**). RED SHARE is the graded
  figure, RED COUNT volume context. **COHORT, one for all three:** the tasks whose `task_closed`
  falls in the window; audit rows joined BY TASK from ANY earlier time, never clipped to the window
  start, but CUT at a RECORDED AS-OF timestamp (the reading time) stated with the reading — a row
  after the as-of never enters that reading, so a re-read at the same as-of reproduces it (E-F3).
  Denominators are NOT shared: audits/done and GREEN-first % divide by that cohort's CLOSURE COUNT;
  RED SHARE divides RED verdict rows by ALL audit verdict rows of the cohort, PER STAGE — the
  pre-stage and post-stage figures are separate and never pooled. **friction/done** —
  deviation-CAPTURE density, direction ambiguous by construction: graded only against its own prior
  ±50%, never as an outcome. **inter-stage elapsed time** via `stage_entered` marks (CONTEXTUAL, not
  graded) — No model-time residual is claimed — the marks cannot produce that split. PAIRED
  TASK-LOCALLY between consecutive marks of the SAME task, LAST mark winning on a retry; a pair is
  ADMITTED by the ts of its FIRST mark; the successor search is cut at a RECORDED as-of timestamp
  stated with the reading, retry marks for one stage collapse to the LAST at or before that cutoff
  BEFORE pairs are formed, and a first mark with no successor by it is CENSORED — counted, never
  imputed; statistic = the MEDIAN per stage pair. **context-economy** P1–P5 — (P1) always-loaded
  seed weight PER AUDIENCE (direction: DOWN), side by side: the Controller's generated
  `HANDBOOK_READ_ORDER` set (EVERY split part; no fixed count) + floor-map + MEMORY.md, AND the
  worker-seed chain + the SAME floor-map. **Bound PER AUDIENCE (E-F4):** the CHARTER §P2
  2000-line WARN is defined over the `HANDBOOK_READ_ORDER` set alone, so it grades ONLY that term of
  the Controller reading (floor-map + MEMORY.md reported beside it, ungraded); the worker chain has
  NO ratified bound and is CONTEXTUAL (direction DOWN, reported, never graded) — SPEC-0127 §5 gives
  a total a trajectory, not a threshold; (P2) stage-bundle weight
  (CONTEXTUAL, not graded until re-based; `binding: stage-entry`, FILTER `status: active`) as the
  DEDUPLICATED UNION of distinct specs over the ACTIVE task-axis stages DEFINED AS OF the snapshot
  sha (the corpus table, not the windowed `stage_entered` rows), plus the per-stage PEAK — never the
  naive per-stage SUM, which double-counts a multi-stage spec. **Unit (E-F5):** BYTES of
  each distinct spec's YAML file at the snapshot sha (`git cat-file -s`), with tokens reported as
  bytes/4 — the CHARTER §P2 estimator — and labelled an estimate; line counts are context only; (P3) session/task cost
  (`token-rollup` cost_usd + `task-scorecard` cost/done); (P4) cache-efficiency as `cache_read ÷
  (input + cache_read + cache_write)` — cache_write IS in the input-side denominator (direction: up;
  CONTEXTUAL — matched-basis movements REPORTED, none graded, no bound) — never the cache_read/input
  RATIO, which moved OPPOSITE to the share 2026-09-20; (P5) cost of undelivered-to-consumption
  content (T2-consumption × P2-weights; input for) — **RETIRED to kind (a) DECLARED-unprobeable
  (C1 exit):** no T2-consumption emitter exists and none is built — reported
  `clean-as-declared`, never NO-DATA; reopen only by filing a card that names and builds that emitter. **Feeds
  (verbatim):** `task-scorecard`, `token-rollup` — RUN FROM THE MAIN CHECKOUT — plus `session
  context` (SPEC-0115) as the live in-session feed, and land `verify_metrics` (wall / intra-run
  per-file `queue_wait_ms`, SPEC-0132) as the verify-cost surface — read PARTITIONED, never pooled: by
  SELECTION MODE and by land OUTCOME, with wall = `verify_wall_ms`, queue = `queue_wait_ms`, each
  reported over its OWN carried/total coverage (they differ: 2,216 vs 1,736 rows 2026-09-20), and
  verify-run DERIVED as wall minus queue **ONLY over the INTERSECTION — rows carrying BOTH fields
  non-null — with that intersection's own carried/total stated; never one field's mean minus the
  other's (E-F2).** SELECTION MODE is a DECLARED field:
  `verify_metrics.selection_governed` (bool), with `selection_govern_reason` when false, folded to
  the values `affected` | `full`; selection RATE = `affected` lands ÷ lands carrying the field.
  **Queue-wait is TWO CLASSES, each with its own field, and is never reported pooled:**
  VERIFY-ADMISSION (between-land) = the heartbeat admission series `graph query admission-series`
  (`views._view_admission_series`, SPEC-0132 Rule 4 — folds the `waiting_for_verify_admission_slot`
  heartbeats per land and names each stream in `instrument.streams`; `admission_wait_ms` is NOT this
  class's field, it under-reports — SPEC-0132 lens `secondary_instrument`);
  LAND-RESERVATION = the SPEC-0119 rule-27 AGGREGATE, which covers ABORTED lands only and carries no
  per-land field: each run reports it AS that aggregate, naming its CURRENT window and carried/total
  and is NOT partitioned until a per-land reservation field exists. `verify_metrics.queue_wait_ms` is
  NEITHER class: it is the INTRA-RUN per-file slot wait inside ONE verify run (the max wait across
  test files under a saturated worker cap, `verify_runner`), read only as the queue term of the
  wall/queue/verify-run split above. Only VERIFY-ADMISSION is partitioned, by `land_completed`
  OUTCOME × `selection_governed`. A null or absent field is NOT a
  zero — it is outside coverage, and each class states carried/total; (admission wait occurs on
  ABORTED lands too). A total SUMMING the classes is not a comparator. **Every datum RECORDED names
  its INSTRUMENT, its BASIS (population + denominator + census coverage) and its extent: a HALF-OPEN
  WINDOW for an event aggregate, or an AS-OF timestamp AND commit sha for a CORPUS SNAPSHOT (P1/P2
  are snapshots; no window applies). A bare number is not a baseline.** A cross-cycle move reads as
  improvement or regression ONLY when the basis MATCHES; otherwise as `basis-changed`, with its
  SIGN, never as a trend. Carried measurements with their basis: P1 seed @2026-09-20 (instrument: wc
  over the generated sets) — as-of commit 44718db9 — Controller 1974 L / 204,450 B / ≈51k tok;
  worker chain + floor-map 1596 L / 169,096 B / ≈42k tok, the worker STARTING baseline — no earlier
  comparable worker reading exists. P2 bundles ≈126k tok @2026-07-17 and ≈271k tok @2026-09-20 are
  BOTH the NAIVE PER-STAGE SUM the P2 clause forbids: P2 reports `no-baseline` until the first
  dedup-union reading, and the two sums are HISTORICAL CONTEXT only — they support no trend and no
  finding. The growth-without-deletion OPEN HIGH (fp
  `always-loaded-protocol-weight-growth-without-deletion`) rests on P1, not on them. **Threshold —
  TWO arms, and they are NOT both live.** Arm 1 cost/closed-task: the ≈$57 @2026-06-17 baseline is
  RETIRED as UNREPRICEABLE — its window, closures, priced total, coverage and rate-table date were
  never recorded, so no fire could be validated. Arm 1 reports `no-baseline` until RE-BASED on a
  window recording all five and naming its rate table; thereafter WARN at > 2× it, both windows
  repriced by ONE named table. **A priced window is USABLE only when ≥ 90% of its token-bearing rows
  are priced by that table (coverage = priced ÷ token-bearing, stated); below it that window reports
  `no-baseline` / no comparison, never a partial rate (E-F6).** Arm 2 median lead-time > 2× a rolling baseline: **RETIRED to kind (a)
  DECLARED-unprobeable (C2 exit)** — no rolling lead-time baseline series is computed or
  stored and none is built (`created_at`→`closed_at` is derivable from the cards; the baseline is
  not). Reported `clean-as-declared`, never NO-DATA and never a finding; reopen only by filing a card
  that computes and stores the series. Arm 1 is the ONLY threshold arm.
- **P6 — seam read amplification (the read-COST axis of context-economy).** What a verb
  costs to RUN, off the counters. **Probe:** the three ratios on `cli_invoked.data.reads` —
  **folds_per_segment** (`folds`/`segments`), **rows_parse_ratio** (`rows_parsed`/`rows`),
  **card_parse_ratio** (`cards_parsed`/`cards`) — WORST-per-seam, never the mean. **Seams graded —
  the population is DERIVED, counterless part included; no name-list appears in this probe.** Grade
  (a) EVERY seam the `reads` counters carry in the window whose WORST ratio exceeds the GREEN bound
  — the set is determined by the BOUND, never a chosen N; (b) every seam named in a `yitc-ops.yaml
  reads.exemptions[]` entry; and (c) the COUNTERLESS set, ENUMERABLE: the PARSER-DERIVED verb
  universe (every invocable leaf of `build_parser`) MINUS those whose `cli_invoked` rows
  carry `data.reads` — a verb that never emits `cli_invoked` is UNMEASURED, never absent. Coverage is graded PER INVOCATION AND PER
  COMPONENT (E-F1): report each verb's TOTAL `cli_invoked` rows beside, for EACH of the
  counters `folds` / `segments` / `rows` / `rows_parsed` / `cards` / `cards_parsed`, the rows carrying
  it; a ratio is computed only over rows carrying BOTH its numerator and denominator, and a verb
  under 100% on ANY component a ratio needs is PARTIALLY instrumented for that ratio and grades with (c). **Thresholds:** GREEN ≤ **1.05**, or ≤ a `yitc-ops.yaml reads.exemptions[]`
  entry's `ratio_bound` when one NAMES that seam (all four of `seam`/`ratio_bound`/`reason`/`until`,
  fail-closed, and `1.05 < ratio_bound ≤ 2.0` — outside it the entry is INVALID) — an exemption
  RAISES the green bound for ALL THREE ratios and waives nothing else; YELLOW above it; **RED >
  2.0** on ANY seam in (a)+(b) — UNWAIVABLE, an exemption never reaches it — **or ANY seam in (c)**
  — an unmeasured seam is RED, not green (M8: «no counters» is its own answer, never a 1.0).
  **Order (rule C):** graded seams are RANKED by BLAST RADIUS first — the count of DISTINCT
  verb names whose `cli_invoked` rows carry that seam's counters in the window — then by worst
  ratio; a ×1 seam under many verbs outranks a high-ratio seam under one. **Remedy:** ONE
  request-scoped **ReadScope at the WIRING SITE**, or a narrower horizon/slice —
  NEVER another per-view cache (SPEC-0190 rule 10). **Feeds (verbatim):** the GRADED feed is
  `bin/yitc-v2 debt --seam-coverage --since <T4 window start> --until <T4 window end>` —
  ONE fold that alone carries the DERIVED population (parser universe → measured / partial /
  UNMEASURED) and each measured verb's worst-per-seam ratios. `bin/yitc-v2 debt` (SPEC-0119 rule-37) and the SPEC-0105 nightly's `seam-reads`
  line are MEASURED-ONLY cross-checks: they fold `debt.seam_read_amplification` over measured seams
  only and carry no counterless population. The GRADED reading is taken over T4's own FIXED ROLLING
  half-open window, so a worst-per-seam value ages out instead of accumulating; the `debt` line's
  7-day fold is a CONTEXTUAL cross-check, labelled with its own window and never the graded figure. A seam whose counters do not span the window reports its
  COVERAGE, not a ratio. **Baseline — LEGACY `basis-changed`:** the 2026-09-04 datum (9/9 seams over
  bound, worst `graph conformance` 5.02x) used the retired name-list population and folds/segment
  alone. Zero point = the FIRST reading over the derived population with all three ratios; until
  then `no-baseline`, not a move.
- **P7 — verify waste (the CAUSE behind the `verify_metrics` cost number).** **Select by
  measurement, REPRODUCIBLY:** (i) every unit at or above **1%** of the table's total, never a
  chosen top-N; (ii) every unit ALSO present in the PRIOR RENDER of that table whose wall grew
  **≥1.25×**, attributed through ONE BATCHED unit→landing-card map per run, never a per-unit
  bisection. That prior render — `tests/verify-durations.json` at the sha recorded by the
  IMMEDIATELY PRECEDING T4 inspection record (no such record or render ⇒ NO growth comparison this
  run) — is the SOLE growth comparator; rule-19 (median of the previous 10 lands) is a DIFFERENT
  basis, routing support only. The statistic is per-unit wall SECONDS from the same field in both
  renders; a unit absent from the prior render is NEW, selectable by (i) only, never by growth.
  **Kernel input:** `tests/verify-durations.json` (SPEC-0132 §6) plus the SPEC-0119 rule-19
  slow-tail growth line in `bin/yitc-v2 debt`. **Consumer input (read-only, `-C <consumer>
  --read-only`):** a consumer is SELECTED only when the SPEC-0105 nightly's rule-19 line names it —
  never by choice. **Count rule (E-F7):** NONE named ⇒ no consumer input this run, stated
  (M8); MORE THAN ONE ⇒ EVERY named consumer is read, each on its OWN window and reported
  separately, never pooled. The set is bounded by the nightly line itself (≤ the registry's
  consumers); NO batched multi-consumer reader exists, so it is one bounded per-consumer read per
  named consumer — the same shape as the production-adoption census above. Each selected consumer's `land_completed.verify_metrics.per_layer_durations` series is read over
  the consumer's OWN half-open land window, stated with the reading — the kernel input is an AS-OF
  SNAPSHOT PAIR of table renders and has no window to share. Per LAYER, the MEDIAN over that
  window's lands; consumer total = SUM of those layer medians. A consumer has no per-file table and
  this probe does not invent one. Read selected units against the waste checklist — single home
  `patterns/consumer-suite-parallelization.md` §The WASTE lever. P7 is CONTEXTUAL: no threshold, no
  count, no new cadence — it rides T4's, its numeric rules SELECT diagnostic units, and the waste
  checklist labels findings rather than any outcome grade. **Order (rule C):** selected units are RANKED by BLAST RADIUS first — the count of DISTINCT
  landing cards the batched unit→card map attributes the unit to — then by seconds. **Record** with
  `inspect record --theme T4 --notes "<units + seconds, each labelled>"`. **Route:** kernel → a card or `followup` id;
  consumer → `cross request`. A run that selected nothing says why (M8).
- **DROP-but-FLAG + the FINDING-UNIT rule.** **Unit:** ONE finding per DECLARED probe whose
  instrument is absent or partial — neither bundling two probes' gaps nor splitting one probe's,
  **Two kinds, and only one is a finding.** (a) A **DECLARED-unprobeable** item — trust / time-saved
  / «friction < v1» (no v1 baseline exists) — is reported `clean-as-declared` each run, NOT as a
  finding: re-raising an accepted gap is noise. (b) An **UN-RETIRED** probe — declared live, but an
  input of it produced by no emitter and never has been — IS a finding: rule A renders it NO-DATA
  every run while nothing is decided. Live instances: NONE. The
  two former ones — **P5** (C1, no T2-consumption emitter) and **threshold arm 2** (C2, no rolling
  lead-time baseline) — were MOVED to (a). A future kind-(b) item takes the same fork: name and build
  the emitter, or move the item to (a).

- **G4 — post-close census:** per episode count abort classes, verb-generated commits and audit passes after close; read every per-project nightly verdict (project_health, born_waivers), not only `seam_reads` — `bin/yitc-v2 journal query --type land_completed` + `bin/yitc-v2 nightly`.

### T5 — Meta-loop health (ceiling-mining, postcheck-aging, roster-currency, MEMORY GC)

- **Surfaces:** captures→promotion→`E-XXXX` FSM; recurrence N≥2; `inspection_completed`; the Review
  re-review scan; postcheck plans; the audit-YAML corpus; MEMORY.md; **age-only terminators** — any
  automated pass that ends plans or removes held worktrees by AGE without reading trigger/hold state.
- **Probes:** every ratio states numerator / denominator / window / reader — capture→case
  (`error_filed`/`deviation_captured`) beside case→disposition (`error_promoted` split by `resolution`);
  E-XXXX state distribution over the file's `status:` (a case with none is its own finding); reopen rate
  (= RCA quality: cases with `reopen_count`>0 / cases ever resolved or waived, all-time) with the
  window's `error_reopened` + `error_residual_recurrence` on WAIVED cases beside it; **audit-ceiling
  pattern-mining** — FULL walk of all passes≥3 + RED cases clustered by root-cause (which finding-classes
  force a 2nd pass; pre↔post asymmetry) — root = the journal `findings[]` where carried (from
  2026-09-08), else the saved YAML `passes_trail` finding_class, coverage reconciled to the group count;
  ceiling-escalation discipline — every pass past the ceiling carries a SPEC-0204 `ceiling_decision` row,
  a `trend_ceiling_grant`, or an EMPTY residual set (a GREEN ceiling row — SPEC-0204), journal
  row AND saved YAML read together (`owner_reset` / consult carriers are pre-2026-09-10 legacy reads);
  the RED-drill SPLITS observation/adhoc audits from task-gate REDs (the conveyor split);
  rung-distribution reads `bg_dispatch_halted.block_classification` over ALL blocked-on-land halts as its
  denominator (`block_classified` has no emitter — a hand-append legacy read), from the MAIN-checkout
  journal (a task-worktree journal misses post-branch folds); the fingerprint-less capture count is its
  OWN probe number beside the singleton ratio; interactive-stall stays a DECLARED uninstrumented blind
  spot (2026-07); **postcheck-aging** of plans (do they soak+close or accumulate — terminal exits split
  by CAUSE: an age-sweep cancel is no soak); **external-auditor reliability** (ABORT-rate — recurrence →
  parked task; **the ABORT-rate is reported PARTITIONED BY CONSULT CLASS and by SPEC-0201 independence
  stamp, never pooled** — the INSPECTION class carries its own number BESIDE the gate-audit class, and a
  pooled-only figure IS the finding (X-0586); the journal `provider` is gate-only, so read the stamp off
  `audit_self_provider_used` + the saved YAML); **roster-currency lens** — «is the inspection list itself
  stale?»: (a) system delta since the last converged refresh (closed tasks / new specs / new verbs / new
  mechanisms read against the calibration point ~220 tasks / ~34 specs / 6 days = DUE (2026-05-31→06-06)
  — report-only, the NEW-cycle cue is the owner's, (d)); **last converged refresh = the 2026-09 cycle
  `plans/inspection-list-refresh-2026-09-delta-recalibratio.md`, its delta measured at cutoff
  : 1807 closures (`journal query --type task_closed --since 2026-07-17`) / 47 new spec
  files (`git log --diff-filter=A -- specs/`) / 66 days since 2026-07-17** (narrow fold precedent:
  2026-06-30, kept for small deltas)); (b) M4-failure (a surface covered by no theme); (c) age of the
  living-criteria home (last commit per served part); (d) accumulated owner-named blind slices
  (owner-worded `owner_directive` rows — covering/preamble rows excluded) → trigger → owner cue for a NEW
  refresh cycle (template = the `inspection-list-refresh` plan); **MEMORY.md buffer GC lens** — the same
  SPEC-0039 §5(c) sweep the weekly backstop runs (one rule, two cadences): flag
  governing-artifact-resolved / orphan / expired-TTL / stale-lead entries; drain-before-delete (never
  delete un-drained durable-worthy content); clean in the run worktree, fold at land.
- **load-sensitive lane over bound? → DISPOSE the global-rework question (SPEC-0132 §3).** Read
  the `debt` echo's load-sensitive-lane line (never recompute the wall by hand). When the lane is OVER
  EITHER bound — its serialized tail past `YITC_LOAD_SENSITIVE_SHARE_PCT` of the duration table's total
  per-file work, or its file count past `YITC_LOAD_SENSITIVE_MAX_FILES` — the review owes a DISPOSITION
  of ONE named global-rework question (box-admission width / stage-6-beside-land policy / harness
  isolation). **Disposition shape:** a DATED line in this week's `inspect record --tier weekly` naming
  the lane's two numbers and choosing either **(a)** the global card it files (by id) or **(b)** why not,
  plus a re-check date. Filing another PER-FILE card is NOT a disposition — a class paid off one instance
  at a time is asking for a rule. Under bound: read the trajectory, dispose nothing. Report-only; the
  rework is the card the review files, if it does.
- **Method:** M9 — separate designed-not-built (the construct) from built-but-not-closing (E-XXXX stuck
  open); fragmentation lens clusters near-duplicate fingerprint families SYSTEMATICALLY (common root, not
  byte-match); verify-package must RE-CARRY raw rows per claim (the auditor is stateless).

- **G5 — autofile + cross + postcheck invariants:** autofile fires once per fingerprint; a cross row whose task is done but not closed; the postcheck window start is reachable — `bin/yitc-v2 journal query --type deviation_captured` + `bin/yitc-v2 cross outbox` + `bin/yitc-v2 debt`.

## The other parts of this roster

- **Part 1** (`patterns/inspection-criteria-roster.md`) — the `CADENCE` values, the
  operational-hygiene weekly checklist, and the T1 / T3 / T7 lens-checklists.
- **Part 2** (`patterns/inspection-criteria-roster-run-and-lenses.md`) — the run-mode, the
  cross-theme method (M1–M9), the foundations and the architecture-drift lens.
- **Part 4** (`patterns/inspection-criteria-roster-portfolio-observation.md`) — the T9
  lens-checklist.
- **Part 6** (`patterns/inspection-criteria-roster-real-work-observation.md`) — the T10 lens-checklist (moved out of part 4 VERBATIM).
- **Part 5** (`patterns/inspection-criteria-roster-themes-integrity-adoption.md`) — the T6 / T8
  lens-checklists (moved out of this part VERBATIM).
- **Navigation map** (`patterns/inspection-criteria-roster-navigation-map.md`) — one row per
  recurring check: check → theme → cadence → how-to-run → rule-home.

This heading also BOUNDS the T5 section above: a theme's freshness hash runs to the next `##`/`###`
heading, so a part must not end on living criteria followed by loose prose — that prose would be
hashed as part of the last theme's criteria.
