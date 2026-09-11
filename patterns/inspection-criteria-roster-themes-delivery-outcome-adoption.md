---
name: inspection-criteria-roster-themes-delivery-outcome-adoption
class: reference
sourced_from: <durable artifact> (SPEC-0120 must-split of patterns/inspection-criteria-roster.md — part 1 re-crossed BOTH one-bounded-read ceilings at 914 lines / 82867 bytes after the and splits; these five lens-checklists re-home here VERBATIM per SPLIT-never-delete) (the reader extension that makes this possible — bin/lib/inspection.py resolves cadence / weekly-tier / per-theme sections across the DECLARED parts in ROSTER_CRITERIA_PART_SUFFIXES, so a moved theme keeps an honest freshness hash instead of a hollowed one) + SPEC-0120 (durable-doc size governance) + SPEC-0057 (the inspection construct — §3 living-criteria home) + patterns/inspection-criteria-roster.md (part 1 — the roster's resolution origin)
applies_to: PART 3 of the single living inspection home (SPEC-0057) — the freshness-hashed per-theme lens-checklists for T2 (instruction↔doc fidelity + delivery/readiness), T4 (outcome / cost-effectiveness), T5 (meta-loop health), T6 (operational integrity) and T8 (adoption). `inspect record --theme T<n>` hashes each section HERE, resolved through the declared-part tuple. Part 1 (`patterns/inspection-criteria-roster.md`) keeps the `CADENCE` values, the operational-hygiene weekly checklist and the T1 / T3 / T7 / T9 / T10 lens-checklists; part 2 (`patterns/inspection-criteria-roster-run-and-lenses.md`) the run-mode + cross-theme method + foundations + architecture-drift lens; the umbrella navigation map is `patterns/inspection-criteria-roster-navigation-map.md`. All four files are ONE living home split for loadability (SPEC-0120). Provider-neutral by rule (CHARTER §P4b).
---

# Inspection criteria roster — part 3 (the delivery, outcome, meta-loop, integrity & adoption lens-checklists)

> **What this IS:** PART 3 of the single living inspection home (SPEC-0057) — the freshness-hashed
> **per-theme lens-checklists** for **T2, T4, T5, T6 and T8**, split out of
> `patterns/inspection-criteria-roster.md` (PART 1) under the SPEC-0120 one-bounded-read ceiling
>. Content is VERBATIM (SPLIT-never-delete): these sections are byte-identical to the ones
> part 1 carried, and `inspect record --theme T<n>` now resolves and hashes them HERE — the reader
> walks the declared parts, so the `criteria_ref` names this file and hashes THIS text.
> No pointer stub was left behind under a `### T<n> —` heading: one section, one home (a second
> claimant makes the resolver refuse rather than silently hash a stub).
>
> **Why THESE five.** The seam is mechanical, not thematic: part 1 keeps every section a test pins
> to *its* filename — the `CADENCE` block and weekly tier (`tests/test_review_due.py`), T3
> (`tests/test_t10935_…`), T7 (`tests/test_t10027_…`), T9 + T10 (`tests/test_t10125_…`), and the T1
> note whose part-1 text `tests/test_t11049_…` scans — and part 3 takes the rest. Moving anything
> else would have meant editing a pinned test to follow the content.
>
> **The other parts:** cadence · operational-hygiene weekly checklist · T1 / T3 / T7 / T9 / T10 →
> **part 1** (`patterns/inspection-criteria-roster.md`). Run-mode · cross-theme method · foundations ·
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
  T2 delivery surface) + **the 2026-07 delivery deltas**: the `session context` threshold echo +
  continuation-seed re-delivery (SPEC-0114/0115), onboarding stations as consume-receipted delivery
  (SPEC-0147 — seeded vs consumed), worker-seed CHAIN completeness (SPEC-0127 — «one part is not the
  seed»: part 1 names all parts AND each exists), and the `debt` echo re-fold (SPEC-0119).
- **Probes:** **DIFF each instruction against the LIVE canon + implementation — «I read it» is NOT a
  fidelity probe** (the entry skill is a KNOWN re-staleness node, N≥3 — check it EVERY run); completeness
  not match; **delivery «worked»** — three-column reconcile promised↔journal↔log (consume ≥3 paths:
  graph query / Read / raw sed-cat; «no event» ≠ «not delivered»); **readiness mechanically** — the
  require-reads gate (SPEC-0050, emits `read_gate_refused`; kinds read-check / stage-correspondence /
  verification-exists per SPEC-0059) — **feeding-view: `bin/yitc-v2 graph query discipline-ratio`**
  (refusal numerator split BY kind over `cli_invoked`; SEPARATE ratio per kind, never one mixed);
  capture the AGGREGATE pattern (a cluster of refusals on one contract/verb = a delivery-redesign
  signal), NOT each refusal (a single refusal = the gate working); **MCP reconcile/floor
  delivery (SPEC-0118)** — the session-start reconcile (list connected → compare vs the declared
  standing set → disable extras) AND the CONNECT/USE `before-mcp-use` floor row are both DELIVERED
  surfaces: check the START echo, the floor-trigger-map row, and the post-`/compact` re-derivation
  pointer (AGENTS §After-/compact MCP reconcile re-delivery) all resolve to SPEC-0118 /
  `working-with-mcp-in-v2.md` and are not stale (a KNOWN co-design-coherence node per SPEC-0007 §5b).
- **Method/evidence-grade:** mark each finding promise-level (promise text ⊂ canon text, grep-provable)
  OR consumption-level (journal/log proves the miss) — NEVER mix (mixing gives false refutations);
  flag **framing-misclassification** (a retired rule presented in instructions as a live principle — a
  defect beyond mere staleness); ABORT-fallback = inline file excerpts into the prompt. Router hygiene
  (F-g2): global <vendor-adapter>.md size/whitelist (≤~40 lines), redirect rule present AND obeyed, no
  re-accretion (durable-form guard = external territory — route on the gate).

### T4 — Outcome / cost-effectiveness (context-economy)

- **Surfaces:** production usage; effort volume + trajectory; friction/rework; M6/M7; token/cost.
- **Probes:** 0-production task count + external `from:`; commits/day trajectory; audits/done, RED
  count, GREEN-first %; friction/done; **model-vs-process time** split via `stage_entered` marks
  (model time vs audit-wait/test-runner); **context-economy** P1–P5 — (P1) always-loaded seed weight
  (wc-sweep of 5 handbook + floor-map + MEMORY.md); (P2) stage-bundle weight (`binding: stage-entry` ×
  FILTER `status: active` — without the filter Analysis over-counts); (P3) session/task cost
  (`token-rollup` cost_usd + `task-scorecard` cost/done); (P4) cache-efficiency (`token-rollup`
  cache_read vs input); (P5) cost of undelivered-to-consumption content (a DERIVED metric of
  T2-consumption × P2-weights — «not consumed» ≠ «waste» without a causal claim; input for
  /delivery-tuning, not a finding by itself). **Feeds (verbatim):** `task-scorecard`,
  `token-rollup` — RUN FROM THE MAIN CHECKOUT (a task-worktree run reads `archive_missing` — the
  `.yitc` archive is per-checkout, 2026-07) — plus `session context` (SPEC-0115) as the live in-session
  feed, and land `verify_metrics` (wall / `queue_wait_ms`, SPEC-0132) as the verify-cost surface.
  **Baselines re-measured 2026-07-17:** P1 seed 1838L/185KB/≈46k tok (2026-06-06: 1329L/97KB/24.8k);
  P2 task-axis bundles ≈126k tok (was 38.6k); headline protocol weight/substantive task ≈172k (was
  ≈63k) — the growth-without-deletion trend is an OPEN HIGH (fp `always-loaded-protocol-weight-growth-without-deletion`). **Threshold (baseline 2026-06-17, est.):** cost/closed-task ≈ $57; WARN if a window's
  cost/closed-task > 2× baseline (~$115) or median lead-time > 2× its rolling baseline.
- **P6 — seam read amplification (the read-COST axis of context-economy).** P1-P5 measure
  what content costs to DELIVER; this measures what a verb costs to RUN — how much of the corpus it
  physically re-reads to answer one question. It was unmeasurable before the counters and is
  read straight off them, so it adds no probe of its own. **Probe:** the three ratios on
  `cli_invoked.data.reads` — **folds_per_segment** (`folds`/`segments`), **rows_parse_ratio**
  (`rows_parsed`/`rows`), **card_parse_ratio** (`cards_parsed`/`cards`) — worst-per-seam, never the
  mean (a seam that reads the corpus 22x once and cleanly 200 times has a mean inside the bound and a
  real defect). **Seams graded:** session start · land tail · `debt` · the `task file` advisory tail ·
  `followup`. **Thresholds:** GREEN ≤ **1.05** — or a `yitc-ops.yaml reads.exemptions[]` entry NAMING
  that seam (all four of `seam`/`ratio_bound`/`reason`/`until`, fail-closed); YELLOW > **1.05**;
  **RED > 2.0** on session start / land / `debt`, **or MISSING counters on a seam that should carry
  them** — an unmeasured seam is RED, not green (M8 presence≠absence; a corpus that has never emitted
  a `reads` row reports «no counters», which is its own answer and never a 1.0). **Remedy — one, and
  it is not negotiable:** the seam's ONE request-scoped **ReadScope at its WIRING SITE**, or a
  narrower horizon/slice. **NEVER another per-view cache** — N caches have N invalidation stories and
  leave the composition itself unmeasured, so proposing one is a proposal to skip SPEC-0190 rule 10,
  which is the rule this probe reports on. **T5 escalation:** when ONE class keeps accumulating
  instance-fix cards — several closures against the same seam family rather than one rule — that is
  the class asking for a rule, not another instance; route it to T5's fragmentation lens.
  **Feeds (verbatim):** `bin/yitc-v2 debt` (the SPEC-0119 rule-37 line, suppressed-when-clean) and
  the SPEC-0105 nightly's per-project `seam-reads` line, both folding the SAME
  `debt.seam_read_amplification` — one oracle, so the two surfaces cannot disagree about a ratio.
  **Baseline (engine, 2026-09-04, the pre-remedy datum):** 9 of 9 measured seams over bound, worst
  `graph conformance` 5.02x folds/segment; across the registry fleet, 33 of 49 on the largest
  consumer. This is the number the axis exists to move, recorded so a later reading has a zero point.
- **DROP-but-FLAG:** trust / time-saved / «friction < v1» = un-probeable (no v1 baseline) — a real
  methodology gap. M8 presence≠absence.

### T5 — Meta-loop health (ceiling-mining, postcheck-aging, roster-currency, MEMORY GC)

- **Surfaces:** captures→promotion→`E-XXXX` FSM; recurrence N≥2; `inspection_completed`; the Review
  re-review scan; postcheck plans; the audit-YAML corpus; MEMORY.md.
- **Probes:** capture/promotion ratio; E-XXXX state distribution (open/resolved/reopened); reopen rate
  (= RCA quality); **audit-ceiling pattern-mining** — FULL walk of all passes≥3 + RED cases clustered
  by root-cause (which finding-classes force a 2nd pass; pre↔post asymmetry); ceiling-escalation
  discipline carried by the SPEC-0124 FSM fields (`owner_reset` / `trend_ceiling_grant` / consult
  events) — probe scopes POST-SPEC-0124 files (legacy pre-2026-07-02 excluded); the RED-drill SPLITS
  observation/adhoc audits from task-gate REDs (the conveyor split); rung-distribution derives from
  BOTH carriers — `block_classified` events AND `bg_dispatch_halted.block_classification` payloads —
  read from the MAIN-checkout journal (a task-worktree journal misses post-branch folds); the
  fingerprint-less capture count is its OWN probe number beside the singleton ratio; interactive-stall
  stays a DECLARED uninstrumented blind spot (2026-07); **postcheck-aging** of plans
  (do they soak+close or accumulate); **external-auditor reliability** (ABORT-rate, interactive-stall
  rate — recurrence → parked task; **the ABORT-rate is reported PARTITIONED BY CONSULT CLASS, never
  pooled** — the INSPECTION consult class carries its own number BESIDE the routine gate-audit class,
  and a pooled-only figure IS the finding. Grounding: X-0586 (boomrocket 2026-08-06) reported that
  pooling hid an inspection-class failure rate inside a 1.5% pooled figure — that percentage is THEIR
  reading of our pooled probe, cited as filed, not a number this roster has re-measured; the
  de-pooling is what makes it measurable here at all); **roster-currency lens** — «is the inspection list itself stale?»:
  (a) system delta since the last converged refresh (closed tasks / new specs / new verbs / new
  mechanisms vs a threshold — calibration points: ~220 tasks / ~34 specs / 6 days = DUE (2026-05-31→06-06) and ~678 closures / 43
  specs / 17 days = the 2026-07 cycle; **last converged refresh 2026-07-17 — the full dual-track
  delta-recalibration cycle `plans/inspection-list-refresh-2026-07-delta-recalibratio.md`, all T1–T10
  re-converged** (narrow fold precedent: 2026-06-30, kept for small deltas)); (b) M4-failure
  (a surface covered by no theme); (c) age of the living-criteria home; (d) accumulated owner-named
  blind slices → trigger → owner cue for a NEW refresh cycle (template = the `inspection-list-refresh`
  plan); **MEMORY.md buffer GC lens** — the same SPEC-0039 §5(c) sweep the weekly backstop runs (one
  rule, two cadences): flag governing-artifact-resolved / orphan / expired-TTL / stale-lead entries;
  drain-before-delete (never delete un-drained durable-worthy content); clean in the run worktree, fold
  at land.
- **load-sensitive lane over bound? → DISPOSE the global-rework question (SPEC-0132 §3).**
  Read the `debt` echo's load-sensitive-lane line (it rides session-start, the land tail and
  `bin/yitc-v2 [-C <repo>] debt` — never recompute the wall by hand). When the lane is OVER EITHER
  bound — its serialized tail past `YITC_LOAD_SENSITIVE_SHARE_PCT` of the duration table's total
  per-file work, or its file count past `YITC_LOAD_SENSITIVE_MAX_FILES` — the review owes a
  DISPOSITION of ONE named global-rework question (box-admission width / stage-6-beside-land policy /
  harness isolation). **Disposition shape:** a DATED line in this week's `inspect record --tier
  weekly` naming the lane's two numbers and choosing either **(a)** the global card it files (by id)
  or **(b)** why not, plus a re-check date. Filing another PER-FILE card is NOT a disposition — the
  whole trigger is that a class paid off one instance at a time is asking for a rule (this lens's own
  T5 escalation). Under bound the numbers still print: read the trajectory, dispose nothing. This is
  report-only and nothing acts on the crossing — the rework itself is the card the review files, if
  it does.
- **Method:** M9 — separate designed-not-built (the construct) from built-but-not-closing (E-XXXX stuck
  open); fragmentation lens clusters near-duplicate fingerprint families SYSTEMATICALLY (common root,
  not byte-match); verify-package must RE-CARRY raw rows per claim (the auditor is stateless).

### T6 — Operational integrity

- **Surfaces:** tests (RED-GREEN; primary owns); `events.jsonl` integrity; graph
  reproducibility; `land`; deps; secrets; read-verb side-effects; worktree session-stamps + claim
  semantics; the `LAND:` token contract; test-host isolation (SPEC-0041) + the 2026-07 verify-infra set: hermetic
  sandbox (SPEC-0131), the verify-admission governor under load (SPEC-0132 — `waiting_for_verify_admission_slot`
  heartbeats vs worker-death class), anti-false-green admission (SPEC-0156), live `--rebaseline`
  discipline (SPEC-0077); **derived-artifact growth vs fixed-offset guards** (a generated artifact
  grows → an unrelated task's guard fires — the / class); session-identity integrity
  (SPEC-0137 ref carry, fail-closed rediscovery); integrity probes read the MAIN-checkout journal;
  B5 declare-or-waive is CONSUMER-scoped (engine-self has no yitc-ops.yaml by design); **MCP external-mutation
  capture** (SPEC-0118 — a substantive external write through any MCP tool must leave a journal line
  like a deploy does).
- **Probes:** tests exit-0 (in a WRITABLE checkout); a **RED-path canary** (deliberate-fail → FAIL+exit
  1 — suite-green alone does not prove failures surface); parse/dedup; ts-backsteps = structural-by-design
  (union-merge interleave at land — parse+dedup, monotonicity is NOT the contract); **in-memory graph
  rebuild ×2 idempotent + diff-vs-committed explainable by new artifacts** (bare `==committed` does not
  hold in a live repo); land ff-only (the «merges» are branch-side update-from-main); **ALL imports
  incl function-level** (the PyYAML miss — not top-level `^import`); secret grep; **stamp check** — the
  `yitc-session-stamp.json` lives in the PRIVATE git dir (`.git/worktrees/<name>/`), not the worktree;
  claim-enforcement proven by TEST NAMES (t0362 4/4 + claim-guard + picker-exclusion), not stamp-file
  presence; **MCP capture-delivery (SPEC-0118)** — for a session that drove a substantive external
  write through an MCP tool, the journal carries the outbound-external-mutation capture line (the
  capture-delivery contract, the `outbound-external-mutation` floor); a silent MCP-driven external
  write is a FINDING (M8 presence≠absence — zero capture-lines is no-data, not proof-of-compliance).
  **Feeds:** `trend-report`. **Threshold (baseline 2026-06-17):** test-leak share 0.0009
  (WARN > 0.01); land_verify median 60s (WARN > 120s); graph rebuild==committed SHA is binary (any
  mismatch = RED).
- **pinned-gate RED triage — which of three causes, and the remedy for each.** A pinned
  last-green gate going RED has three causes with three different remedies, and reaching for the
  wrong one is how a gate gets weakened to make a red go away. Classify BEFORE acting (SPEC-0191
  §5 block-classification; the default under uncertainty is STOP):
  - **2a — TIMING.** The red is a wall-clock / admission-wait artifact, not a subject failure: the
    assertion is about duration, or the test lost its slot under SPEC-0132 contention. **Remedy:**
    re-run under the admission path; if it REPRODUCES, hermetize or bound the offending test **at
    source** (SPEC-0131). **Never widen the timeout** — that converts a measurable flake into an
    invisible one, and the widened bound outlives everyone who remembers why.
  - **2b — CORPUS-CENSUS.** A census / count assertion drifted because the CORPUS grew, and the diff
    never touched the counted subject (the / derived-artifact-growth-vs-fixed-offset
    class). **Remedy:** REBASELINE the pinned last-green, with the mechanical tie — the diff, the
    named assertion, the pre-existing audited artifact — recorded in `--rebaseline-reason`
    (SPEC-0077 §3a incidental staleness, LIFECYCLE §Two-flow-types carve-out). Only on a **fresh
    GREEN audit-post**; never a silent bump, and never as a way past 2c.
  - **2c — CHANGED-SUBJECT.** The diff really did move the asserted subject: this is a TRUE SIGNAL
    and the gate is doing its job. **Remedy:** fix **in scope** and re-audit the new commit. Where
    the cause is OUT of scope or environmental, `blocked-on-land` with the **verbatim failing
    assertions** (SPEC-0103) — the contracted escalation is the correct outcome, not a failure.
    Never weaken, skip or delete the assertion to pass.
  **The classification is evidence-bearing, not a vibe:** 2b is the only one a worker may
  self-clear, and only on the mechanical tie above; an unproven flake, a deliberate guard, or ANY
  uncertain block is a HALT (SPEC-0191 §5 three-rung ladder). **Probe:** the share of pinned-gate
  reds carrying a recorded classification — an unclassified red is itself the finding, since a red
  cleared without a named cause is indistinguishable from a gate quietly weakened.
- **B5-delta — waiver-vs-real-command coherence (grounding: trend-finder B5):** a `yitc-ops.yaml`
  declare-or-waive section WAIVED while the repo carries a real, wired command for it is an incoherence
  FINDING — e.g. `tests:` waived while `bin/verify.sh` exists AND the `land` is test-gated. A waiver
  must not contradict a present capability; reconcile (declare it) or justify the waiver explicitly.
- **land-verify concurrency stability (weekly; grounding: the 2026-07-03 concurrency flake class —
  oversubscription + ff-race — that SPEC-0132 governs).** The durable, recurring successor to the
  proposing plan's one-week post-Z real-data watch, so that flake class cannot silently drift back.
  Two report-only reads over the recent `land_completed` A4 verify-metrics window (SPEC-0132 Rule 2 /
  SPEC-0025), REUSING the shipped pure signal — **no new store/detector/parser** (CHARTER §P1):
  (a) the SPEC-0132 Rule-3/4 watch-point signals via `bin/lib/worktree.py#_verify_scaling_signals`,
  and (b) a scan of that window's `fail_class`. **FINDING criterion is precise:** a non-ok
  `fail_class` is a FINDING only when **RECURRING** (the same non-ok class ≥ 2× in the window) OR
  **NON-DETERMINISTIC** (≥ 2 distinct non-ok classes = class-switching flakiness); a lone one-off
  non-ok class is a report-only observation, not a finding. **report-only — never an autonomous
  action (CHARTER §6 fence);** the owner/Review decides whether to act. Run:
  ```
  python3 -c 'import sys,json,collections; sys.path.insert(0,"bin")
  from lib.worktree import _verify_scaling_signals
  rows=[json.loads(l).get("data",{}) for l in open("events.jsonl") if "\"land_completed\"" in l][-200:]
  fc=collections.Counter((d.get("verify_metrics") or {}).get("fail_class","ok") for d in rows)
  bad={k:v for k,v in fc.items if k not in ("ok",None)}
  recurring={k:v for k,v in bad.items if v>=2}
  nondet = len(bad)>=2
  print("window n=%d fail_class=%s" % (len(rows), dict(fc)))
  if recurring or nondet:
      print("FINDING: land-verify fail_class instability — recurring=%s non-deterministic=%s" % (recurring or "none", nondet))
  elif bad:
      print("observation (report-only, not a finding): lone one-off non-ok class(es)=%s" % bad)
  else:
      print("fail_class: clean — no finding")
  print("scaling signals:", "\n".join(_verify_scaling_signals(rows)) or "none — clean")'
  ```
  (Run from a repo checkout — the window is the last ~200 `land_completed` rows; widen the slice if a
  longer look-back is wanted. Signals may fire report-only on scaling watch-points independent of
  `fail_class` — SPEC-0132 Rules 3-4.)
- **abort assertion legibility — what share of aborts can NAME what broke (weekly; report-only;
  grounding: kupiclub X-1050, who measured 96 of 133 assertion entries (72%) reading
  `(no assertion captured)` across 105 aborted lands).** The sibling bullet above asks whether the
  verify is STABLE; this one asks whether its refusals are LEGIBLE. **It is not a legibility nicety,
  and that is what earns it the weekly slot:** a `land --rebaseline` waive token must NAME an
  assertion, so a MUTE abort leaves the token nothing to bind to and the land ends at a human — the
  origin of that project's 61 waive-coverage refusals. One root, two symptoms, neither visible
  without the fold. REUSES the shipped pure signal `bin/lib/worktree.py#_abort_assertion_legibility`
  — **no new store / detector / parser / event / gate** (CHARTER §P1), and it reads back the very
  markers `_surface_failing_assertions` writes.
  **METHOD — the part both sides paid to learn, and the part not to "simplify":** fold on the **TEXT**
  of `failing_assertions` and **NEVER on `abort_class`**. `abort_class` is a ROUTING label, not a
  measurement bucket: it unions refusals of different PLACEMENT and different MOVABILITY, so a share
  computed from it measures the taxonomy instead of the legibility (that hazard is its own card). And **bound the window to the CURRENT layer configuration** — folding across a layer
  REMOVAL mixes a layer that no longer exists into today's diagnosis; the fold opens its window after
  the newest row recorded under a removed layer and SAYS how many rows that excluded. A repo with no
  `verify.layers` declaration is told there is no boundary to apply, never that the bound was clean.
  **NO THRESHOLD IS DECREED, and that is measured rather than shrugged:** this kernel reads 2.5% mute
  over its last 300 aborted lands, kupiclub read 72% over theirs — two orders of magnitude on the
  same fold, so any cross-repo number would be voluntaristic. The share is a TRAJECTORY the
  owner/Review reads; **report-only, never an autonomous action** (CHARTER §6 fence / SPEC-0057 §2),
  and it moves no exit code. The three entry buckets (named / mute / unshaped) and the row-level
  "carried no `failing_assertions` at all" count are never added together — each absence is a
  different absence. The CAUSE side is not duplicated here: fixes the column-zero banner
  matcher, one source of mute aborts on this side. Run:
  ```
  import sys, os, json
  root = sys.argv[1] if len(sys.argv) > 1 else "."
  sys.path.insert(0, os.path.join(root, "bin"))
  from lib.worktree import _abort_assertion_legibility
  rows = [json.loads(l).get("data", {})
          for l in open(os.path.join(root, "events.jsonl"), encoding="utf-8", errors="replace")
          if '"land_completed"' in l][-300:]
  layers = None # or the names in this repo's yitc-ops.yaml `verify.layers[].layer`
  print("\n".join(_abort_assertion_legibility(rows, current_layers=layers)["report"]))
  ```
  (Run as `python3 <this block> /path/to/repo` — pure stdlib beyond the kernel module it imports, so
  the SAME block runs under `-C <consumer>` over that repo's own journal. A consumer passes its
  declared layer names as `layers` to get the configuration bound; leaving it None reports that no
  boundary applies rather than pretending one did. **The carrier key is `layer`** — until
  this block named a `name` key on those entries — a key that does not exist — and a consumer following it
  verbatim got `[None, None...]`, which the fold then read as a real declaration: it reported
  `0 of 0... (None%)` and excluded that repo's two BUSIEST LIVE layers as "no longer declared",
  while the correct key over the same journal read 75% mute (kupiclub X-1145). A declaration that
  resolves to no usable name is now **REFUSED and says so** rather than folded — still report-only,
  still no exit code; passing `None` remains the honest way to say "I am declaring nothing".)

**T6 sub-lens — parallel-landing health (weekly; report-only; grounding: the kernel SPEC-0161
recorded-set freeze of 2026-08-21 · the consumer suppressor kupiclub found on their first non-empty
formation, X-1072 / · the same day's fleet overrun, 11 workers against a printed advisory
width of 8).** Every other landing surface is per-BRANCH, per-TASK or per-SESSION; none asks whether
PARALLEL landing is working AT ALL. So a congestion regime is discovered by whoever happens to be
landing into it, at full verify cost, instead of at a scheduled read. This lens closes that by folding
the two events the batch path already emits — `land_batch_formed` and `land_completed` — into one
weekly read. **Report-only, manual-first, NEVER an autonomous action** (CHARTER §6 fence / SPEC-0057
§2); it introduces no store, no event, no verb and no gate.

**Read it right — three rules, each of which the controller's own first fold got wrong:**
1. **A SOLO BATCH IS NOT BY ITSELF A DEFECT.** The head holds the slot and cannot be skipped, and
   dropping peers protects them from a batch the head's diff already dooms. shipped
   VISIBILITY only and changed no behaviour. Formation width is therefore REPORTED as a
   **trajectory** and is deliberately **not a finding criterion** — a solo-share criterion was built,
   measured against real windows, and REMOVED because it fired on a healthy one.
2. **`stale-wait-row` IS NOT AN EXCLUDED BRANCH.** It is a historical wait row correctly discarded as
   outside the freshness window, and it outnumbers the real exclusions by ~6x (669 vs a true top of
   117 on 2026-08-21). Ranking it beside them inverts the whole reading, so the fold counts it
   separately and says so.
3. **`engagement` tells you whether batching was even ENABLED.** All 105 of that day's kernel
   formations read `kernel-authored-verify` — batching was on, so whatever made those heads ineligible
   was NOT the engagement switch. On a consumer the same field is what exposes a suppressor
   (kupiclub's window reads a mix of `project-authored-verify-undeclared` /
   `-declared-unsafe` / `project-declared-combined-candidate-safe`).

**The per-BRANCH and per-CAUSE reads are NOT re-implemented here — run `bin/yitc-v2 [-C <repo>] debt`**
and read its rule-26 line (one abort cause refusing several different branches — the entry point for
"what actually froze it"), rule-23 (dead lands), rule-24 (branches ahead of main) and rule-27 (what
the aborts cost). Those are, windowed, consumer-capable views; this lens CITES them and adds
only the cross-cutting fold they have no place for (CHARTER §P5). Note when reading rule 26 that in a
busy repo it is routinely non-empty — it is a good *cause* lookup and a poor congestion *detector*,
which is why the finding criterion below is the zero-success stretch instead.

**FINDING criteria — measured, not decreed, and only two:** (a) a **CONGESTION REGIME** — >= 5
distinct branches aborted across a stretch of >= 60 min in which NOTHING landed; (b) the **abort share
ROSE >= 15 pp** vs the preceding window of equal length (both windows >= 20 terminal lands). Replayed
over seven consecutive real kernel days these fire on 2026-08-21 alone (7 branches / 73 min, +21 pp)
and are silent on 2026-08-16..20, whose worst stretches run 2-4 branches. Everything else printed is
trajectory, not verdict.

**Runs against ANY repo — pass the repo root, so a consumer runs it unchanged over ITS OWN journal**
(`python3 <this block> /path/to/consumer`); it is pure stdlib and resolves no kernel path. Optional
2nd/3rd args replay a window: `<end-ISO> <days>`. A repo with no rows in the window says so explicitly
rather than reading "clean". Run:
```
import sys, os, json, collections, datetime
root = sys.argv[1] if len(sys.argv) > 1 else "."
F = "%Y-%m-%dT%H:%M:%SZ"
end = sys.argv[2] if len(sys.argv) > 2 else datetime.datetime.now(datetime.timezone.utc).strftime(F)
days = int(sys.argv[3]) if len(sys.argv) > 3 else 7
e1 = datetime.datetime.strptime(end, F)
b1, b0 = (e1 - datetime.timedelta(days=days)).strftime(F), (e1 - datetime.timedelta(days=2*days)).strftime(F)
form = {"window": [], "prior": []}; land = {"window": [], "prior": []}
for line in open(os.path.join(root, "events.jsonl"), encoding="utf-8", errors="replace"):
    if '"land_batch_formed"' not in line and '"land_completed"' not in line: continue
    try: ev = json.loads(line)
    except Exception: continue
    ts, t, d = ev.get("ts", ""), ev.get("type"), ev.get("data") or {}
    w = "window" if b1 <= ts < end else ("prior" if b0 <= ts < b1 else None)
    if not w: continue
    if t == "land_batch_formed": form[w].append(d)
    elif t == "land_completed": land[w].append((ts, d.get("status"), d.get("branch")))
if not form["window"] and not land["window"]:
    print("parallel-landing: no land_batch_formed / land_completed rows in %s.. %s — nothing landed in this repo in the window (report-only, not 'clean')" % (b1, end)); sys.exit
def solo_pct(f):
    return round(100 * sum(1 for d in f if (d.get("members") or 0) <= 1) / len(f)) if f else "n/a"
def abort_pct(l):
    return round(100 * sum(1 for r in l if r[1] == "abort") / len(l)) if l else "n/a"
f, l = form["window"], land["window"]
qd = sorted((d.get("queue_depth") or 0) for d in f)
exc = collections.Counter; stale = 0
for d in f:
    for x in (d.get("queue_excluded") or []):
        r = x.get("reason") or "?"
        stale += (r == "stale-wait-row")
        if r != "stale-wait-row": exc[r] += 1
print("window %s.. %s (prior = the %dd before it)" % (b1, end, days))
print("[a] formations n=%d width=%s solo=%s%% (prior %s%%) queue_depth med=%s max=%s engagement=%s"
      % (len(f), dict(sorted(collections.Counter((d.get("members") or 0) for d in f).items)), solo_pct(f),
         solo_pct(form["prior"]), qd[len(qd)//2] if qd else 0, qd[-1] if qd else 0,
         dict(collections.Counter(d.get("engagement") or "none" for d in f))))
print(" real per-branch exclusions (ranked): %s" % (exc.most_common(6) or "none"))
print(" stale-wait-row: %d — a historical wait row correctly DISCARDED, NOT an excluded branch; never rank it beside the above" % stale)
print("[b] terminal lands n=%d ok=%d abort=%d abort share %s%% (prior %s%%)"
      % (len(l), sum(1 for r in l if r[1] == "ok"), sum(1 for r in l if r[1] == "abort"), abort_pct(l), abort_pct(land["prior"])))
l.sort; bounds = [b1] + [r[0] for r in l if r[1] == "ok"] + [end]; worst = (0, 0.0, "")
for x, y in zip(bounds, bounds[1:]):
    br = {r[2] for r in l if x < r[0] < y and r[1] == "abort"}
    mins = (datetime.datetime.strptime(y, F) - datetime.datetime.strptime(x, F)).total_seconds / 60
    if (len(br), mins) > (worst[0], worst[1]): worst = (len(br), mins, x)
print("[c] worst zero-success stretch: %d distinct branch(es) aborted over %.0f min from %s" % worst)
find = []
if worst[0] >= 5 and worst[1] >= 60:
    find.append("CONGESTION REGIME — %d distinct branches aborted across %.0f min in which NOTHING landed (from %s); read the cause with `bin/yitc-v2 debt` rule-26 line, then fix it ON MAIN" % worst)
if len(l) >= 20 and len(land["prior"]) >= 20 and abort_pct(l) - abort_pct(land["prior"]) >= 15:
    find.append("abort share ROSE %d pp (%d%% -> %d%%) vs the prior window" % (abort_pct(l) - abort_pct(land["prior"]), abort_pct(land["prior"]), abort_pct(l)))
# Formation WIDTH is deliberately NOT a finding criterion: the head holds the slot and cannot be
# skipped, and dropping peers protects them from a batch the head's diff already dooms ( —
# visibility only, no behaviour change). Width is REPORTED in [a] as a trajectory, never judged.
print(("FINDING: " + " | ".join(find)) if find else "no trajectory finding — [a]/[b]/[c] above are the TRAJECTORY, not a verdict on any one formation")
```
(Default window: the last 7 days, compared against the 7 before it. A repo that has not turned
batching on has no `land_batch_formed` rows — section [a] is then empty and [b]/[c] still apply.)

**T6 sub-lens — exercise-the-gated-paths (monthly; report-only; grounding: X-0366 / plan
`anti-false-green-doctrine-differential-proven-chec`).** The rest of the revizia model READS artifacts
(docs/specs/journal/graph) — but **a gate that never fires cannot fail a check, so a never-walked path
rots unpassable INVISIBLY** (X-0366: aiseller's owner-gated deploy hid an unpassable security gate until
an 8h prod-auth outage forced it, and a declared verify layer was green-for-owner + structurally
impossible for any other user). This lens closes that blind-spot by periodically **EXERCISING** the
gated/rarely-walked paths in a **NON-mutating dry-run**, instead of only inspecting the artifacts that
describe them. It is **report-only, manual-first, NEVER an autonomous action** (CHARTER §6 fence /
SPEC-0057 §2 — a dry-run exercise is still an OBSERVATION: owner-invoked, non-blocking); the owner/Review
decides whether an unpassable path is a finding. Adds **no new construct / verb / event / store** — it
reuses the shipped dry-run seams below.

| Lens | Surfaces | Probes |
|---|---|---|
| **exercise-the-gated-paths** | the gated/rarely-walked paths a corpus read never walks: the deploy guard shape · a declared `verify.layers[]` coverage boundary · the onboarding-delivery seam | the 3 exercises below (each NON-mutating) |

- **Exercise (a) — deploy guard shape (dry-run):** run `bin/yitc-v2 deploy --print-guard` — the EXISTING
  governed dry-run seam (SPEC-0094 §1; `bin/lib/deploy.py`): it emits the guard-snippet machine contract
  a consumer embeds in its `deploy.sh`, **WITHOUT a live deploy** (no code change; the parent card's
  illustrative "deploy check-shape" == the shipped `--print-guard`). The guard shape still RESOLVES ⇒ the
  gate that only fires on a real deploy is not silently broken. A non-resolving / malformed guard = a
  finding.
- **Exercise (b) — a `verify.layers[]` layer AS A NON-owner (dry-run):** run a declared verify layer as a
  **non-owner user** (a verify/test execution — non-mutating). The false-green class this catches:
  a layer that is green FOR THE OWNER but structurally impossible for any other user (X-0366 #5) — a
  coverage boundary a corpus read of `verify.layers[].covers` cannot. A layer that only the owner's
  environment can pass = a coverage-boundary finding (SPEC-0093 / SPEC-0152).
- **Exercise (c) — the onboarding-delivery seam (read-only):** confirm the onboarding seam still DELIVERS
  a due station — the seam nudge / `session start` onboarding digest RENDERS the due station
  (`_onboarding_seam_nudge` / `_onboarding_digest`, read-only, no consume), OR run
  `bin/yitc-v2 memory consume --station <id>` against a **DISPOSABLE fixture station only** (the exercise
  consumes NO live MEMORY.md pointer → no durable corpus mutation). A seam that no longer surfaces a due
  station = a finding (the rarely-walked delivery path rotted).
- **Probe null ≠ clean (F-#2):** a clean result NAMES which gated paths were exercised (deploy guard
  resolved / a layer ran as non-owner / the onboarding seam rendered), never a bare "none".

### T8 — Adoption (done = adopted)

- **Surfaces:** verb invocation (MAP verb→effect-event); feature adoption (views, `--projected`/
  `--as-of`, `journal query`); P8 evidence (`consumer_read_evidence`/`live_trigger_evidence`) vs
  closures; the SPEC-0038 observation SUB-lens (per-task `post_verification` of done tasks — plan-born
  read within the plan's `postcheck` window, work-first read standalone); `task_closed`
  `post_verification_gap` markers.
- **Probes:** built-and-not-invoked list; P8-evidence / closure ratio; saved-view query count; **per
  SURFACE** (base vs advanced/recovery — aggregate «closed/not-closed» is FORBIDDEN: base may be ×16.6
  adopted while advanced is built-not-invoked); distinguish recovery-only verbs from routine (a low
  recovery-lens count is NOT a defect; `--as-of` = PROVISIONAL recovery-by-design pending one real
  Review-recovery-flow check, no force-adopt); SPEC-0038 fill-vs-forget rate (observe-only, no
  graduation/causal claims); F-#3 re-check (is the grep-fallback still needed or did views close it).
  **Sub-lens records OBSERVATIONS ONLY — no verdicts, no graduation, no status writes; NOT its own theme**
  (it stays a T8 sub-lens — distinct from the T9 capability-graduation theme below, which owns the
  kernel↔consumer capability-portfolio decision).
  Map verb→actual effect-event or get a false «never invoked» (M2 — re-proven 2026-07: argv/verb-string
  greps over `cli_invoked` false-zero; verify the key shape first). 2026-07 adoption map additions:
  `debt` · `memory seed|consume` · `task refuse` · `worktree recover-land`/`adopt` · `quiesce` ·
  `dispatch --watch`/fleet-verdict · `followup arm|unarm` (each → its effect-event) + onboarding
  station consumption rate (seeded vs `onboarding_station_consumed`) + the SPEC-0149 post-deploy-proof
  debt view.

**T8 sub-lens — reverse-adoption (runtime-vs-) (monthly; report-only; grounding: X-0366;
calibrated 2026-07-18, dual-track blind-first —).** T8 above reads adoption in ONE direction:
**shipped → invoked** — every probe starts from something the corpus says was SHIPPED and asks whether
it was used. The **reverse** direction is unread: **live runtime code that was never governed-deployed**.
Nothing in the corpus points at it — no closure, no P8 evidence, no `deploy_completed` to start from —
so a corpus-only read cannot see it (X-0366: a container recreate silently shipped main to prod; the
not-adopted view had no reverse notion; 8h outage while every corpus-reading check stayed GREEN). Same
shape as the T6 blind-spot, one axis over: **a divergence the corpus has no record of cannot be read out
of the corpus.** It is **report-only, manual-first, NEVER an autonomous action** (CHARTER §6 fence /
SPEC-0057 §2 — a reverse probe is still an OBSERVATION: owner-invoked, non-blocking); the owner/Review
decides whether a divergence is a finding. Adds **no new construct / verb / event / store** — it reuses
the shipped read-only seams below; it never deploys, reconciles, or mutates anything.

| Lens | Surfaces | Probes |
|---|---|---|
| **reverse-adoption (runtime-vs-)** | what is LIVE but has no governed-deploy provenance: deployed-state vs `deploy_completed` history · post-deploy proof debt · live-probe reachability vs declared surface · host-config reconciliation drift | the 4 probes below (each read-only) |

- **Probe (a) — live state vs `deploy_completed` provenance.** For each project declaring a deploy
  contract, compare what is RUNNING against the journal's `deploy_completed` history. A live surface
  with **no** `deploy_completed` carrier = runtime that reached prod outside the governed seam — the
  X-0366 class. Read-only: the journal + the project's declared deploy contract (SPEC-0094 §1).
  *Cause-side sibling:* the implicit-shipping-path topology (bind mounts / mutable tags) is watched by
  the shipped runtime-delivery declaration + mount advisory — this probe catches the
  RESULT when that path fired.
- **Probe (b) — post-deploy-proof debt (SPEC-0149).** Read the SPEC-0149 post-deploy-proof debt view
  (already surfaced by `bin/yitc-v2 debt`). A deploy whose proof never landed is a shipped-but-unproven
  runtime claim — the reverse-direction sibling of a closure with no P8 evidence.
- **Probe (c) — live-probe reachability vs DECLARED surface.** Run the per-change `live_probe` GET
  (`bin/yitc-v2 liveprobe`, non-mutating) against what the corpus DECLARES is live. A probe that
  resolves to a surface no closure accounts for — or a declared surface no probe can reach — is a
  divergence. (Distinct from T6's exercise (b): that asks "can a non-owner PASS this gate?"; this asks
  "does the corpus ACCOUNT for what answers?")
- **Probe (d) — host-config reconciliation drift (SPEC-0111).** Compare the recorded
  `host_reconciliation_recorded` evidence against the host's current config. Live host config with no
  reconciliation record = host state that diverged from its governed apply seam.
- **Probe null ≠ clean (F-#2):** a clean result NAMES which reverse probes ran and what each resolved
  (deploy provenance matched for projects X/Y · proof-debt view empty · live probe reached the declared
  surface · host reconciliation current), never a bare "none". A probe that could not RUN is reported as
  **not-run**, never folded into "clean" — that conflation is the false-green this lens exists to catch.

**T8 sub-lens — exemption-case revision: «is the mechanism and its feedback alive?» (monthly;
report-only; SPEC-0178 rules 7+9).** A project may declare, in its own `yitc-ops.yaml`
`audit_scrutiny.cases[]`, named cases whose matching cards close WITHOUT the Stage-8 audit-post. That
declaration is an accepted risk, and the thing that keeps it honest is not a cap — the owner declined
outer caps (CHARTER §Project-declared audit-post exemption) — but a periodic look at whether the
mechanism is still doing what the project thought it was. A T8 sub-lens rather than a theme of its own
because this IS T8's question one surface over: T8 asks whether a shipped thing is actually being
used, and this asks whether a declared exemption is still warranted **and whether the feedback that
would tell us has anyone left making it**. Adds no store, no verb, no cadence of its own.

**Run it:** `bin/yitc-v2 inspect record --theme T8 --tracks primary,external` (or `--dry-run` to read the block without
recording a run) — the `inspection_completed` event carries the report-only `case_review` block, one
proposal per declared case. Under `-C <consumer>` it folds THAT consumer's carrier and journal; the
kernel declares no ops contract, so its own run reports «0 declared» and that is the correct answer,
not an empty result.

| Lens | Surfaces | Probes |
|---|---|---|
| **exemption-case revision** | `yitc-ops.yaml audit_scrutiny.cases[]` · `task_closed.data.exempted_case` (the closure end) · `task_closed.data.case_out_of_path` (rule 6) · `deviation_captured` attributions (the rule-5 join) | the four-field proposal + the covered share below |

- **The PROPOSAL format (rule 7) — four fields, never three.** Every proposal names the **CASE**, the
  **ACTION** (`restore` · `narrow` · `widen` · `leave`), the **BASIS** (the specific records) and the
  **STRENGTH** of that basis — either **direct observation** or **absence of observation**. The verb
  derives a CANDIDATE action; the human decides. `widen` is never machine-proposed: rule 7 says the
  review does not compute whether to loosen.
- **Absence is labelled, and is NEVER read as safety.** A case with no defect judgement against it
  surfaces as a `restore` candidate whose strength is *absence of observation* — because zero
  attributions means EITHER nothing escaped OR nobody made the call, and no record distinguishes
  those. This is the same F-#2 discipline as the reverse-adoption lens above, applied to a population
  rather than a probe; treat a quiet case the way you treat a probe that could not run.
- **Read the UNCOUNTED captures, not only the counted ones.** Case-linked captures carrying no `kind`
  are the difference between «nothing happened» and «nobody looked». The block reports them separately
  with the reason each does not count — that split is the actual liveness signal, and a count of
  records is not a probe of the thing that produces them (`lessons/a-presence-count-is-not-a-liveness-
  probe`).
- **Why this lens exists at all (measured, cycle 15).** End-to-end over four projects' entire history,
  the automatic restoration chain collapses to **zero** at the `kind: defect` triage hop on all three
  consumers. So wherever that judgement is not made, the automatic brake never fires and **this review
  is the restoration carrier**. It is a weaker promise than an automatic one and a TRUE one.
- **The covered SHARE (rule 9) — report-only, over the case's OWN `window_days`.** Each case reports
  the share of closed cards it actually exempted over its own W (kernel default 90), NOT since the last
  review: the median inter-review gap is 0 days on all four projects, so a since-last-review
  denominator is usually empty (cycle 19). **No ceiling, no threshold, nothing refused** — a wide share
  still accepts every close. Two consecutive reviews therefore compare like-for-like periods, and the
  DRIFT between them is the signal a reviewer weighs: a case creeping from 10% to 40% has changed what
  the project is accepting without anyone re-deciding it. An empty denominator reports **undefined**,
  never 0% — a measurement not taken must not read as a reassuring one.
- **What the reviewer decides.** Nothing here is applied. Take each proposal to the project: keep it
  (`leave`), tighten the declared `paths:` (`narrow` — rule 6's out-of-path rows are the evidence for
  this one), or put the gate back (`restore`, always an owner act — re-declaring a restored case is
  never automatic). A `widen` is a fresh project decision, made with the share in front of you.

## The other parts of this roster

- **Part 1** (`patterns/inspection-criteria-roster.md`) — the `CADENCE` values, the
  operational-hygiene weekly checklist, and the T1 / T3 / T7 / T9 / T10 lens-checklists.
- **Part 2** (`patterns/inspection-criteria-roster-run-and-lenses.md`) — the run-mode, the
  cross-theme method (M1–M9), the foundations and the architecture-drift lens.
- **Navigation map** (`patterns/inspection-criteria-roster-navigation-map.md`) — one row per
  recurring check: check → theme → cadence → how-to-run → rule-home.

This heading also BOUNDS the T8 section above: a theme's freshness hash runs to the next `##`/`###`
heading, so a part must not end on living criteria followed by loose prose — that prose would be
hashed as part of the last theme's criteria.
