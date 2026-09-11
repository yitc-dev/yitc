---
name: inspection-criteria-roster-run-and-lenses
class: reference
sourced_from: <durable artifact> (SPEC-0120 must-split of patterns/inspection-criteria-roster.md — the roster exceeded the 800-line / 63000-byte single-read ceiling; this is PART 2, split at a coherent seam, content VERBATIM per SPLIT-never-delete) + SPEC-0120 (durable-doc size governance) + patterns/inspection-criteria-roster.md (PART 1 — the umbrella roster map + per-theme lens-checklists this part serves alongside)
applies_to: PART 2 of the single living inspection home (SPEC-0057) — the run-mode, the cross-theme method (M1–M9), the inspection foundations, the architecture-drift lens, and the scope-clarification / why-a-pattern orientation + drain / what-homes-elsewhere pointers. PART 1 (`patterns/inspection-criteria-roster.md`) holds the cadence + the operational-hygiene weekly checklist + the T1 / T3 / T7 / T9 / T10 lens-checklists; PART 3 (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`) holds the T2 / T4 / T5 / T6 / T8 lens-checklists; the umbrella navigation map is `patterns/inspection-criteria-roster-navigation-map.md`. The files are ONE living home split for loadability (SPEC-0120). Provider-neutral by rule (CHARTER §P4b).
---

# Inspection criteria roster — part 2 (run-mode, cross-theme method & lenses)

> **What this IS:** PART 2 of the single living inspection home (SPEC-0057), split from
> `patterns/inspection-criteria-roster.md` (PART 1) under the SPEC-0120 one-bounded-read ceiling
>. Content is VERBATIM (SPLIT-never-delete). PART 1 remains the cadence + the
> operational-hygiene weekly checklist + the T1 / T3 / T7 / T9 / T10 lens-checklists, and **part 3**
> (`patterns/inspection-criteria-roster-themes-delivery-outcome-adoption.md`)
> carries the T2 / T4 / T5 / T6 / T8 lens-checklists; THIS part carries the run-mode, the cross-theme
> method, the inspection foundations, the architecture-drift lens, and the orientation + drain/homes
> pointers. Each rule it maps homes elsewhere (cited inline, never restated — P5 / SPEC-0005 rule 8).


## On an «inspection» request — CLARIFY scope first (do not silently pick a tier)

When the owner asks for a «inspection», **ASK inline first** (recommendation-first, never a
form — AGENTS §Recommendation-Default) BEFORE running. Do **NOT** silently default to a tier: a bare
«sdelai reviziyu» ("run an inspection") is **NOT** self-evidently the light tier, and running only it (0 `inspection_completed`
events) is **not a revizia** — it is the failure this rule closes (the ai-gateway 2026-06-24 incident).

Clarify **two** things:

1. **Quick or full?** — **full is a SUPERSET of quick, NOT a mutually-exclusive fork.** A full revizia
   does everything a quick one does AND adds the substantive theme sweep on top; it NEVER skips the
   cheap actionable hygiene sweep (parking-lot / blocked-queue / overdue-recheck / born-waiver
   freshness …). Choosing «full» never trades away the hygiene checks — it layers the analysis over them.
   - **quick** = the **weekly operational-hygiene checks ALONE** — the weekly-cadence subset of
     §Operational-hygiene (parking-lot / blocked-queue / MEMORY GC / read-gate ratio / canary …); light
     ongoing hygiene, NOT the substantive analysis. (The monthly / per-session rows of that tier are
     their own cadence, not part of «quick».)
   - **full** = that **same weekly operational-hygiene sweep** (the quick tier, run in full) **PLUS**
     the **T1–T10 system-inspection sweep** — ALL 10 themes via §Run-mode + the per-theme lens-checklists,
     emitting **`inspection_completed`** per theme (the substantive analysis). The hygiene sweep is the
     FLOOR of a full run; the T1–T10 analysis is layered on top, never instead of it.
2. **Triage afterward?** — whether to also run **`bin/yitc-v2 triage run`** (sweep + route the un-routed
   captures the inspection surfaces). **Default: yes** after a full revizia (findings need routing);
   optional after a quick one.

**Carve-out — no clarification needed:** a **migration-complete / baseline** revizia is **ALWAYS full +
triage** (it is defined: onboarding runbook **§B5 facet 3**). Ask only for an ad-hoc «inspection».

## Why a pattern, not a plan (the P7 fix this closes)

A `plans/<slug>.md` carries an FSM (`draft → … → realized | partial | rejected`). When such a plan
reaches `realized` it is **terminal** — historical record + pointer only (SPEC-0034 §realized). So a
plan can NEVER be the *permanent* home of LIVING criteria: at its realize, that content would be
orphaned in a terminal carrier (the P5 one-home / P7 contradiction captured as deviation
`living-criteria-home-hosted-in-realized-terminal-plan`). A **non-FSM pattern** has no terminal state,
so it is the correct stable home. **SPEC-0057 §3 points HERE** for the inspection living-criteria home.
The drain is now **COMPLETE** : the roster + run-mode + per-theme lens-checklists live HERE.

## Run-mode — how an inspection run executes (drained from the realized roster plan)

The pinned discipline (the runbook STEP 2 chains it; this is its living home):

- Each theme runs **DUAL-TRACK** — a **primary track** and an **external track**, INDEPENDENTLY, on
  the **same matrix** (the theme's checklist below); finding sets are compared **AFTER both tracks
  finish** (comparing during run lets anchoring eat the independence).
  - **RECORD which tracks ran — pass `--tracks`, every run** : the run's
    `inspection_completed` carries that coverage only if the operator says so, so record the run with
    `bin/yitc-v2 inspect record --theme T<n> --tracks primary,external`. OMIT it and the run reads
    **coverage NOT RECORDED** — which is not a claim that both tracks ran, and is exactly how a
    half-run reads identical to a converged one in the journal (the 2026-08-13 cycle: `inspect
    record` emitted for T1–T10 while only two themes had a second track). The flag's contract — the
    accepted names, the refusal on an unrecognised one, the coverage-is-not-a-grade fence — lives in
    `bin/yitc-v2 inspect record --help`; this is the cue to USE it, not a second home for it.
- **The first external pass of each theme is BLIND** (raw data, no primary candidates — its own
  analysis); verify/refute mode only from the second pass (method-lesson M5 / T3 run-1).
- **RUNNABILITY PRECONDITION — check the blind track's INPUT CLASS before launching it, not after two
  ABORTs.** A blind pass consumes RAW DATA of a specific class; when that class does not exist for the
  theme, the blind track is **NOT-RUNNABLE**, and that is a fact readable BEFORE the consult, not one
  to discover by trial. So: name the theme's blind-track input class, check it is present and
  non-empty, and if it is absent **do not launch** — record the track as `no_data` naming the missing
  input class, and run the theme single-track with the gap stated. **Put that gap in the RUN, not
  only in prose:** record the single-track run as `inspect record --theme T<n> --tracks primary` —
  naming the one track that ran — so the missing track is readable off the event instead of resting
  on the operator having narrated it. The case that produced this rule:
  a **runtime-probe theme with no primary transcripts** (T10-shaped — its raw data IS the observed
  worker×auditor transcript). An operator meeting it for the first time burnt **two ABORT passes**
  learning that blind-with-no-evidence is unrunnable, each burning a full auditor wall-clock and
  routing a verdict artifact to the escalation archive as durable noise (X-0577, boomrocket
  2026-08-06). A trial ABORT is not a cheap probe. NOTE the division of labour: SPEC-0173 rule 1
  already fixed how an empty result READS (`no_data` is rendered, so an ABORT cannot pass as
  externally-audited-and-clean) — this precondition is about what an unrunnable track COSTS to
  discover, which that rendering contract does not address.
- **Track divergence on a theme = a weakness in the LIST** (a single-track finding is a blind spot of
  the checklist) → amend the checklist HERE → re-run, until the finding sets converge.
- **Editing a theme's checklist AFTER it converged returns the theme to re-run** — converged covers
  only the run checklist (F-#2 null≠clean).
- Findings flow into the **one nonconformity sink** as real captures: `captured_via: inspection`, with
  `inspection_theme`, source-independent `fingerprint` (SPEC-0056). Each theme run emits exactly **one
  `inspection_completed`** event (`criteria_ref` = the run-checklist hash; SPEC-0025). Inspection is
  **read-only observation, not a gate** (SPEC-0057 — the construct home; established by): a run
  mutates neither corpus nor code.
- **Evaluation = the findings, NOT a color** (SPEC-0057 §4): output IS the findings list, each tagged
  HIGH/MED/LOW + the surface. NO per-theme GREEN/YELLOW/RED. The only per-theme signal is the derived
  binary `open HIGH? yes/no`; prioritize a theme with an open HIGH on a load-bearing surface first.
- **ORDER candidates by BLAST RADIUS as well as by count — a count-only sort buries the cluster that
  matters.** Recurrence count answers *how often*; it does not answer *what does this
  compromise*. Rank on BOTH axes and let blast radius break the tie: a candidate touching a
  **verification instrument** (the hermeticity of the probes, the sandbox, the sweep itself) outranks a
  higher-count candidate on a **contained** surface, because a defect in the instrument makes every
  other reading in the run untrustworthy. **CLUSTER BEFORE YOU SORT**, by COMMON ROOT and not by
  byte-identical fingerprint (the M9 fragmentation lens) — a real family whose members each carry a
  near-unique fingerprint stays scattered across a dozen ×1 rows and can never reach the head of a
  count-sorted list, so an ordering rule applied to unclustered rows changes nothing. This is the same
  **blast-radius-not-size** doctrine LIFECYCLE §Two flow types applies to gate weight and SPEC-0072
  applies to effort tier, on a third axis: candidate ORDER (one principle, three axes — not a new one).
  Grounding: the 2026-08-13 run routed its window by recurrence count alone. The count-sorted head was
  the `land-verify-timeout:<test>` family (one contained, well-understood surface); the
  probe-hermeticity family — verification instruments mutating live state, sandbox leaks, a hermetic
  patch left inert — sat at ×1–×2 per fingerprint and was buried, though it compromises the instrument
  every other finding that run was measured with. Executable form + the differential:
  `dev-utilities/reference-revizia-sweep-constructor.py` (`cluster_captures` / `rank_candidates`, with
  the count-only ordering kept beside them as the named control).
- **Instrument degrade — REPORT a surface the run could not READ (SPEC-0173 rule 4).** When a theme's
  instrument cannot read its **watched subject** — an undecodable doc, an unparseable record, a probe
  whose output never arrived — that subject is **reported as DEGRADED, naming the subject and the
  cause**, and is **never** dropped from the report and **never** counted as swept. Dropping it makes
  the run read as a *smaller clean corpus*: the instrument's silence gets read as the subject's health,
  which is the false CLEAN of F-#2 one level up (the instrument, not the subject). The obligation binds
  the filter's DESIGN and is discharged by running it once against a **deliberately broken watched
  subject** — break the SUBJECT, not the filter — and observing that it emits. The kernel's own
  reporting surfaces render this through one named face (`bin/lib/inspection.py` §THE NAMED DEGRADE),
  inheriting the live-revision adapter's shape: name the degrade, keep the fallback, never zero.
  **The rule's set is CLOSED** — the inspection result renderers, the audit-verdict rendering, and this
  reporting prose. **Wrapper monitors and the ad-hoc checks a session writes for itself are OUT** (owner
  decision 2026-08-08): they cannot be enumerated, so a rule over them could never be discharged. They
  are governed **as a HABIT** instead, and it is a live one — during this rule's own trial four
  session-authored filters misreported, including a liveness check keyed on a *wrapper* process id that
  called a live `land` dead and a wait-loop whose pattern matched a word inside the plan's own slug. The
  habit: **arm the healthy control and see it FIRE before you read the broken arm** (a silent instrument
  and a mis-armed probe are indistinguishable from the output alone), and **key a waiter on the SUBJECT**,
  never on a wrapper or a substring.
- **CONSTRUCT the sweep from the theme's DECLARED probe roster — an absent instrument gets a NO-DATA
  line, never a silent omission.** Build the sweep by ENUMERATING the theme's declared probes
  and opening **one section per probe BEFORE any of them runs**. A probe whose instrument does not exist
  in this repo/window emits its own explicit line — `NO-DATA: <probe> — instrument absent: <instrument>`
  — and that line is part of the report. **Absence is STATED; it is never inferred from silence.**
  What this RETIRES: building the sweep by iterating whatever the probes happened to return. Under that
  construction an OMITTED probe and a CLEAN probe render identically, so a probe that never ran reads as
  one that ran and found nothing — and the sweep silently becomes shorter than its own roster.
  **Discharge it the way the instrument-degrade rule above discharges its own — by DIFFERENTIAL, not by
  reading the prose:** run the constructor once with one instrument deliberately removed and SEE the
  NO-DATA line; with the rule dropped, the same run must read clean. Both halves, or you cannot tell a
  working constructor from a silent one (`lessons/a-presence-count-is-not-a-liveness-probe` — arm the
  healthy control and watch it FIRE before you trust the broken arm).
  **Adjacent, not a duplicate — three rules, three different steps.** The instrument-degrade rule above
  (SPEC-0173 rule 4) governs a probe that IS in the sweep but could not read its subject; F-#2 below
  governs how a no-cause RESULT reads. This one governs whether the probe entered the sweep AT ALL —
  the step upstream of both, and the one neither reaches.
  Grounding: the 2026-08-13 T5 sweep omitted three of its own mandated probes (external-auditor
  reliability, roster-currency, MEMORY GC) — and **one of them had FIRED**. The primary track could not
  see the omission; only the blind external track caught it, which is the evidence that the defect was
  in what the sweep was BUILT from and not in how its output was read. Executable form:
  `dev-utilities/reference-revizia-sweep-constructor.py` (`construct_sweep`, with the retired
  present-only construction kept beside it as the named differential control).
- **VALIDATE BEFORE YOU REPORT — every finding, every realm (the step, not a caveat).** Before a
  candidate is filed as a **FINDING**, answer both halves out loud: **(a) WHICH exact field, file or
  command asserts it**, and **(b) what does that source actually MEASURE?** A candidate that cannot
  name BOTH is filed as a **CANDIDATE**, not a finding — the label is the whole differential, and a
  mechanical pass whose inputs were not read first yields candidates by default. **The
  validate-before-report pass is where the work is; skipping it files false findings as real.**
  This binds on **every realm SPEC-0057 §9 names** — the **kernel's own run**, a **kernel→consumer
  `-C` run**, and a **consumer's own project revizia** — and is stated realm-agnostically on purpose:
  it was scoped to consumer runs while the kernel run had no such step, and the kernel run is where
  it was then measurably needed. It is the run-wide face of **M2** (validate the PROBE before
  reporting); M2 is the same discipline stated per-probe, this one binds per-FINDING.
  - **Two measured groundings, both real runs.** On a CONSUMER (boomrocket 2026-08-06, X-0666 — own
    colliding id namespaces, non-kernel test layout, own YAML shapes) the T1 mechanical candidate pass
    ran at a **5-of-5 FALSE-POSITIVE rate**; all five died under the validate pass. On the **KERNEL's
    own run** (2026-08-13) a validation pass over the 26 cards that run filed found **10 needing
    correction — a 38% defect rate**, and every one was the same failure: a signal reported without
    reading what the signal measures (`events.jsonl` `deviation_captured` ts=``,
    fingerprint `revizia-findings-38pct-defect-rate-no-validate-step-before-filing`).
  - **The worked failure — read the FIELD, not the plausible name.** Four land findings of that run
    rested on **`queue_wait_ms`**, which measures the longest a single **TEST FILE** waited for one of
    the parallel workers **inside one run** — an intra-run scheduling tail where nothing is idle or
    reclaimable. The field that measures the **between-land** wait is **`admission_wait_ms`**, and by
    it **84 of 87 lands (97%) waited exactly zero**. Same-shaped name, different subject; the report
    said "99% of lands blocked on verify admission" and the truth was the opposite. Two fields, one
    unread — that is the whole class.
- **Emit-isolation:** a full run is a long batch → emit ALL its events from ONE `work/<slug>` worktree
  and fold once at `land` (SPEC-0055 §Batch-run journal isolation; the single from-anywhere ad-hoc
  capture reflex is the excluded case).
- **Full-run FLOOR — the hygiene sweep is IN the run checklist (superset, not a fork):** a **full** run
  ALWAYS runs the complete weekly operational-hygiene sweep (all §Operational-hygiene weekly rows —
  parking-lot / blocked-queue / overdue-recheck / born-waiver freshness …) as the floor UNDER the T1–T10
  themes, independent of theme rotation. Those hygiene rows are part of the **run checklist that
  `criteria_ref` hashes** (`<roster>#<theme>@sha`, §6), so every full-run theme's `inspection_completed`
  **`criteria_ref` CARRIES the quick-tier checks** — with **`lenses_covered`** enumerating them as the
  companion field. This reuses the existing §6 event fields — NO new store, verb, or event (P1). A quick
  run runs the hygiene sweep ALONE; a full run can never silently drop it.

## Cross-theme method — the durable lessons M1–M9 (apply to EVERY theme, either track)

M1 inspect the IMPLEMENTATION + all named surfaces (never `--help`/prose) · M2 validate the PROBE
before reporting (map a verb to its ACTUAL effect-event) · M3 completeness, not match · M4 enumerate
the full surface list up front · M5 a single-track finding = a METHOD gap (record the missed surface) ·
M6 RUN the verdict-gating chronology · M7 RUN the claimed-artifact-exists enumeration (M6/M7 =
RUN-not-RECALL) · M8 presence≠absence (repo-zero = no-evidence, not proof-of-absence) · M9 classify
each zero as designed-not-built (roadmap) / built-but-not-working (defect) / built-but-not-invoked
(adoption gap) / built-but-unobservable (the subject exists and may well have been invoked, but leaves
no trace on the available surface).

**M2's derivation — the verb→event map is DERIVED from the EMITTERS, never hand-listed.**
M2 states the obligation (map a verb to its ACTUAL effect-event); it does not state where the map comes
from, so it is satisfiable from recollection — and a recollected event name that does not exist yields
a **confident ZERO**, which is worse than an error: an error stops the run, a false zero is filed as a
finding and costs a triage cycle. So **derive the map, then classify every name BEFORE you count it**:

```
grep -rhoE '_?append_event\(\s*"[a-z_]+"' bin/lib/*.py bin/yitc-v2 | grep -oE '"[a-z_]+"' | tr -d '"' | sort -u
```

A name you are about to count must land in exactly one of three buckets. **(1) in-repo emitter** — it
appears in that set; count it in `events.jsonl`. **(2) shared-store emitter** — it is emitted to the
kernel-owned SHARED coordination store, not this repo (the `cross_*` family, whose emitter tables live
in `bin/lib/cross.py`; SPEC-0084 / SPEC-0086), so its in-repo zero is the **CORRECT** reading and the
count comes from the shared fold `bin/yitc-v2 cross outbox` / `cross inbox`. **(3) emitted nowhere** —
that is a **DEFECT IN THE SWEEP, not a measurement**: fix the name, and never report its zero.
Bucket (2) is not a footnote — it is the second, quieter failure mode, where the name is real and the
zero is still meaningless.
Grounding: the 2026-08-13 T8 sweep counted `plan_staged`, `followup_captured` and `cross_requested` and
reported three zeros. The first two are emitted nowhere; the third is bucket (2). Their real in-repo
subjects are `plan_stage_entered` and `followup_added`. **Derive them — do not transcribe them from
this paragraph**: hand-copying the corrected names is the same defect one generation later, and the
recorded figures (871 and 441 rows at the run's own ts ``) are a fixed-window
provenance record, not a live count — they have grown since, which is exactly why a replay names its
cutoff. Executable form: `dev-utilities/reference-revizia-sweep-constructor.py`
(`derive_event_map` / `classify_event_name` / `count_events`).

**M9's fourth bucket — built-but-unobservable (SPEC-0173 rule 3, the vocabulary is that rule's, not a
local synonym).** A subject known to exist but **not observable through the available surface** is
recorded in this bucket — **never** as "absent" / "never invoked", and **never silently dropped** from
the sweep. Both of those alternatives re-create the false-verdict defect one level down: filing it as
never-invoked is a false FINDING that costs a triage cycle, and quietly excluding it from the sweep is a
false CLEAN. They look identical to a good run, which is why the bucket is the fix rather than sharper
operator judgement.

- **Worked example (P4-run-1, a real subject with a witness).** The `land` repeated-abort
  acknowledgement flag is BUILT (read at two call sites in the worktree module) and was INVOKED
  in-session on a real task, where the repeated-abort backstop was live and only the acknowledgement
  could clear it. It is nonetheless UNOBSERVABLE: the resulting successful `land_completed` carries no
  acknowledgement field of any kind, so nothing in the journal distinguishes that land from an ordinary
  one. Under the first three buckets an inspector asking «is this flag ever used?» is forced to file it
  built-but-not-invoked. It belongs in the fourth.
- **Counting caveat (the method trap from the same run).** **The presence of a token in a journal
  payload is not invocation evidence.** A naive grep for that flag name returned 227 hits — every one a
  prose mention inside a halt or deviation payload, not an invocation record. Counting them would have
  produced the opposite and equally false conclusion («heavily used»). Establish invocation from an
  effect-event the invocation itself writes (M2: map a verb to its ACTUAL effect-event); when no such
  effect-event exists, that absence IS the unobservable finding — record the bucket, do not infer a
  count from prose.

## Inspection foundations — use the artifacts, know the blind spots (F-#1/#2/#3)

- **F-#1 — one examination family:** inspection + the per-deliverable audits + the per-session
  aspect-audit share one lens / one sink / one root-vocabulary; findings cluster across themes (D6).
  Coherence is T1's job at the corpus altitude.
- **F-#2 — «null ≠ clean»:** a no-cause result classifies no-problem vs no-data (blind) — a clean run
  MUST carry swept-surface evidence (which files/globs were walked), never a bare "none found"; a
  no-data result names the missing instrument (SPEC-0056 §3).
- **F-#3 — prefer the artifacts; grep is a defect-marked fallback:** prefer repo-native artifacts
  (graph query / journal query / saved views / verbs) when they work; a manual grep is an ALLOWED but
  DEFECT-MARKED fallback that itself emits an observability-gap capture. SEQUENCE: fix/adopt the
  artifacts FIRST, then mandate their use.

## Architecture-drift lens (audit baseline SPEC-0080; lens SPEC-0081)

A themed lens in the SPEC-0057 inspection roster — it audits the corpus's **CODE** (not docs) for
conformance to the SPEC-0080 code-architecture evolution principles (extraction-not-accretion /
realize-the-declared-seam / report-not-block). **Audit baseline = SPEC-0080; lens spec = SPEC-0081;**
probe shape per SPEC-0057 §5 (PROBE-ONLY). Converged over a 2-cycle dual-track trial (run-refs
`inspection_completed#run_ref=arch-drift-lens-trial-run-1`/`-run-2`). **Grounding incident:** the
`bin/yitc-v2` monolith (~20,800 lines, never-built CHARTER §P5 `bin/lib/state.py`) caught only because
the owner asked (`decisions/monolith-split-readiness-audit-adhoc.yaml` = YELLOW). Landed by
(plan `architecture-drift-inspection-lens-extends-spec-00`). Models the report-only posture of the
`discipline-ratio` / `canary-backstop` / `displacement-retention` lenses.

| Lens | Surfaces | Probes (each → a CANDIDATE finding, never a block — SPEC-0080 P-A6) |
|---|---|---|
| **Architecture-drift** | the engine corpus's CODE — `bin/` + any `*.py` / `*.sh` | the 3 surface-probes below |

- **Probe 1 — SIZE (P-A1):** a code FILE past SPEC-0080 §Trigger-surface's **line budget** is a
  candidate. (Threshold BY POINTER to SPEC-0080 — never restated here; P5 / SPEC-0005 rule 3.)
- **Probe 2 — DUPLICATION (P-A1):** a coherent **subsystem** (state I/O, a verb family, a prompt
  builder) copy-pasted past SPEC-0080 §Trigger-surface's **duplication threshold** is a candidate.
- **Probe 3 — UNREALIZED DECLARED SEAM (P-A2):** a charter/spec-PROMISED module left unbuilt is a
  candidate **regardless of counts** (canonical instance: CHARTER §P5 `bin/lib/state.py`).

**Report-only + finding-quality (NOT extra surfaces).** Output = a read-only verdict + candidate list
recorded as an `inspection_completed` event carrying a **`run_ref`** (as its trial runs did —
`run_ref=arch-drift-lens-trial-run-1`/`-run-2`), NOT via `inspect record --theme architecture-drift`:
the `inspect record` theme guard's kernel allow-set is the fixed **T1..T10** roster (`bin/lib/inspection.py`
`THEMES`), and the engine repo has no `yitc-ops.yaml` consumer-declared-theme escape hatch, so the
`architecture-drift` slug is REFUSED there — the `run_ref`-tagged event IS its sanctioned record path
(the lens has no T-slot; it stays a run-ref-recorded report-only lens). NEVER a pre-commit gate /
land blocker (SPEC-0080 P-A6; CHARTER non-goals #2/#7). Two refinements ride the SAME three surfaces:
(a) **null ≠ clean** (F-#2) — swept-surface evidence, never a bare "none found"; (b) **P-A3 admission**
— each candidate notes whether an extraction would actually DELETE duplication / reduce reasoning cost;
a candidate failing P-A3 is low-value (surface it but do not fatigue the reviewer).

**Knob-calibration loop (governed — SPEC-0081).** The lens's hit-rate + false-positive counts ARE the
calibration data for SPEC-0080 §Trigger-surface's provisional knobs. A knob CHANGE lands via a
`spec edit` to SPEC-0080 (the before-rule-change chokepoint); a knob KEPT lands via the
`inspection_completed` evidence citing the data. **Current calibration (trial runs 1–2): confirmed-keep
the SPEC-0080 §Trigger-surface seed values (no change)** — clean separation on the current corpus, with the
caveat that the single-outlier corpus leaves the size UPPER bound + duplication sensitivity unexercised.

## Drain obligation — homed elsewhere (pointer only, P5)

The drain-at-realize RULE (when/what must drain into this home before a plan reaches `realized`) lives
SINGLE-HOME in **SPEC-0034 §realized**; the finalization auditor check lives in **SPEC-0036
`PLAN_FINALIZATION_LENS`**. This pattern is only the destination HOME — it does NOT restate the
obligation (P5 one-home, SPEC-0005 rule 8).

## What homes elsewhere (cite, do not restate)

- The inspection CONSTRUCT (what an inspection IS + its invariants + §9 cadence model): **SPEC-0057**.
- The consumer-local theme declare-shape + the `view:` XOR `sweep:` probe KINDs (the §Consumer-local
  product-adaptation-themes home POINTS here): **SPEC-0093 rule 12**; the NON-NORMATIVE
  product-adaptation framing it adapts: **SPEC-0057 §9**.
- The drain-at-realize RULE (the gate this home is the target for): **SPEC-0034 §realized**.
- The launch/sequencing + triage procedure: `patterns/inspection-triage-launch-runbook.md` (it READS
  this roster — STEP 2 — it does not re-host it).
- The `inspection_completed` event schema: **SPEC-0025**; the nonconformity sink + triage routing +
  the four routes: **SPEC-0056** + AGENTS; the triage-run window + batch-emit isolation: **SPEC-0055**.
- The displacement-retention sweep (T7 surface): **SPEC-0052** / ****.
- The drift-capable-vs-drift-proof CLASSIFIER the T1 drift-possibility sub-probe applies: **SPEC-0067**.
- The code-architecture evolution principles the Architecture-drift lens audits: **SPEC-0080** /
  **SPEC-0081**.
- The durable-doc governance rule the T7 size+language sub-probe measures (English-only kernel + the
  400–500-line band + the consumer methodology-vs-product path rule): **SPEC-0120**.
- The audience-scoped seed mechanism the T7 worker-seed audience-guard sub-probe reads (the section
  `<!--AUDIENCE:...-->` tags + the three generated views + the two-part HARD PROBE): **SPEC-0127**;
  the generated inventory it reads: `graph/worker-startup-inventory.md` (built by `graph build`).
- The trial/calibration HISTORY of how these checklists converged: the realized plans
  `inspection-list-refresh-2026-06-fresh-roster-lense.md` + `inspection-revizia-concept.md` +
  `inspection-theme-calibration-cycle-dual-track.md` (history, NOT a live list).
